import unittest
from queue import Queue
from unittest.mock import MagicMock, patch

from vue_api.kdzn_hciqa.engine_dependencies.graph_rule_queries.general_graph_queries import (
    find_general,
    resolve_theme_label_with_permission,
)
from vue_api.kdzn_hciqa.engine_dependencies.graph_rule_queries.general_query_state import (
    GeneralQueryCache,
    GeneralQueryStateStore,
    SearchResult,
)
from vue_api.kdzn_hciqa.engine_dependencies.graph_rule_queries.tog_path_explorer import (
    TogSearchContext,
    _build_initial_path_query,
    _call_tog_qwen,
    _extract_json_object,
    _parse_tog_selection,
    _resolve_cached_path,
    _validate_graph_label,
    get_path_direction,
    query_path,
    query_path_extend_one_hop_backward,
    run_tog_search,
)
from vue_api.kdzn_hciqa.engine_dependencies.kdzn_graph_qa_engine import kdzn_qa


GENERAL_MODULE = (
    "vue_api.kdzn_hciqa.engine_dependencies.graph_rule_queries."
    "general_graph_queries"
)
TOG_MODULE = (
    "vue_api.kdzn_hciqa.engine_dependencies.graph_rule_queries."
    "tog_path_explorer"
)


class GeneralGraphQueriesTests(unittest.TestCase):
    def test_initial_tog_query_uses_parameter_and_validated_label(self):
        query = _build_initial_path_query("shebeijianxiu_6000701")

        self.assertIn("n:shebeijianxiu_6000701", query)
        self.assertEqual(query.count("$match_entity"), 2)
        with self.assertRaises(ValueError):
            _validate_graph_label("label`) MATCH (n) //")

    @patch(f"{TOG_MODULE}.query_path", return_value=([], [], [], []))
    def test_path_extension_parameterizes_node_names(self, query_path_call):
        node_name = '设备"}) MATCH (n) RETURN n //'
        path_text = f"{node_name}-[包含]->部件"

        query_path_extend_one_hop_backward(
            "shebeijianxiu_6000701",
            path_text,
            "设备检修",
        )

        query = query_path_call.call_args.args[0]
        self.assertNotIn(node_name, query)
        self.assertIn("$path_node_0", query)
        self.assertEqual(
            query_path_call.call_args.kwargs["parameters"],
            {"path_node_0": node_name, "path_node_1": "部件"},
        )

    @patch(f"{TOG_MODULE}.query_new_neo4j", return_value=[])
    def test_query_path_forwards_parameters_to_neo4j_client(self, query_neo4j):
        parameters = {"match_entity": '设备"名称'}

        self.assertEqual(
            query_path("MATCH (n {name: $match_entity}) RETURN n", "设备检修", parameters),
            ([], [], [], []),
        )
        query_neo4j.assert_called_once_with(
            "MATCH (n {name: $match_entity}) RETURN n",
            parameters=parameters,
            kg="",
        )

    def test_extract_json_object_accepts_wrapped_model_output(self):
        self.assertEqual(
            _extract_json_object('结果如下：```json\n{"result": "over"}\n```'),
            {"result": "over"},
        )

    def test_invalid_cache_decision_falls_back_to_tog(self):
        self.assertEqual(_resolve_cached_path("模型暂时不可用"), "TOG")
        self.assertEqual(_resolve_cached_path(""), "TOG")

    def test_invalid_path_selection_keeps_all_candidates(self):
        self.assertEqual(
            _parse_tog_selection("非 JSON", 3),
            (False, [0, 1, 2], {}),
        )
        self.assertEqual(
            _parse_tog_selection('{"result":"over","selected_ids":[1,9]}', 3),
            (True, [1], {"result": "over", "selected_ids": [1, 9]}),
        )

    @patch(f"{TOG_MODULE}.get_top_matches")
    @patch(f"{TOG_MODULE}._call_tog_qwen", return_value='{"result":"over"}')
    def test_tog_cache_over_skips_vector_search(self, _call_qwen, get_top_matches):
        cache = GeneralQueryCache()
        cached = SearchResult(True, ["结果"], ["入口-[关系]->结果"], [[]], [], [])
        cache.replace([cached])
        context = TogSearchContext(
            label_with_id="shebeijianxiu_6000701",
            file_ontology="设备",
            scene_choose="设备检修",
            rewritten_query="查询结果",
            is_multi_turn=True,
            top_k=2,
            fuzzy_entity="入口",
            max_rounds=3,
        )

        results = run_tog_search(
            "规则未命中",
            context=context,
            cache_manager=cache,
            embedding=object(),
            event_queue=Queue(),
        )

        self.assertEqual(results[0], cached)
        self.assertEqual(len(results), 2)
        get_top_matches.assert_not_called()

    @patch(f"{TOG_MODULE}.call_qwen_messages", return_value=None)
    def test_tog_qwen_uses_central_client_and_normalizes_empty_answer(self, call):
        self.assertEqual(_call_tog_qwen("选择路径"), "")
        call.assert_called_once_with([{"role": "user", "content": "选择路径"}])

    def test_query_states_are_isolated_by_session_and_file_scope(self):
        store = GeneralQueryStateStore()
        first = store.get("conversation-1", "文件甲")
        first.replace([SearchResult(False, ["结果甲"], ["路径甲"], [[]], [], [])])

        self.assertEqual(store.get("conversation-2", "文件甲").get_paths(), [])
        self.assertEqual(store.get("conversation-1", "文件乙").get_paths(), [])
        self.assertEqual(store.get("conversation-1", "文件甲").get_paths(), ["路径甲"])

    def test_clearing_session_removes_all_its_file_scopes(self):
        store = GeneralQueryStateStore()
        first = store.get("conversation-1", "文件甲")
        second = store.get("conversation-1", "文件乙")
        other = store.get("conversation-2", "文件甲")

        store.clear("conversation-1")

        self.assertIsNot(first, store.get("conversation-1", "文件甲"))
        self.assertIsNot(second, store.get("conversation-1", "文件乙"))
        self.assertIs(other, store.get("conversation-2", "文件甲"))

    def test_expired_query_state_is_rebuilt(self):
        store = GeneralQueryStateStore(ttl_seconds=1)
        original = store.get("expired", "文件甲")
        original.updated_at -= 2

        self.assertIsNot(original, store.get("expired", "文件甲"))

    def test_cache_selects_aligned_result_data(self):
        cache = GeneralQueryCache()
        cache.replace(
            [
                SearchResult(
                    False,
                    ["结果甲", "结果乙"],
                    ["路径甲", "路径乙"],
                    [[("甲", "关系", "结果甲")], [("乙", "关系", "结果乙")]],
                    [("根", "包含", "甲")],
                    [(0.9, "入口实体")],
                )
            ]
        )

        selected = cache.get_result_by_path("路径乙")

        self.assertEqual(selected.result_names, ["结果乙"])
        self.assertEqual(selected.paths, ["路径乙"])
        self.assertEqual(selected.path2triplet, [[("乙", "关系", "结果乙")]])
        self.assertEqual(selected.path_triplets, [("根", "包含", "甲")])
        self.assertEqual(selected.matched_entities, [(0.9, "入口实体")])

    def test_find_general_wrapper_writes_session_scoped_cache(self):
        store = GeneralQueryStateStore()
        result = SearchResult(
            False,
            ["结果甲"],
            ["路径甲"],
            [[("入口", "关系", "结果甲")]],
            [("入口", "关系", "结果甲")],
            [(0.9, "入口")],
        )
        with (
            patch(f"{GENERAL_MODULE}.general_query_states", store),
            patch(f"{GENERAL_MODULE}._find_general", return_value=[result]),
        ):
            returned = find_general(
                "6000701",
                object(),
                "重写问题",
                "文件甲",
                "设备检修",
                "入口",
                "关系",
                False,
                object(),
                object(),
                3,
                5,
                session_id="qid-1",
            )

        self.assertEqual(returned, [result])
        self.assertEqual(store.get("qid-1", "文件甲").get_paths(), ["路径甲"])
        self.assertEqual(store.get("qid-2", "文件甲").get_paths(), [])

    def test_get_path_direction_detects_outgoing_center_entity(self):
        direction = get_path_direction(
            "变压器-[异常现象]->吱吱声",
            [(0.9, "变压器（油浸式）")],
        )

        self.assertEqual(direction, "backward")

    def test_get_path_direction_detects_incoming_center_entity(self):
        direction = get_path_direction(
            "设备-[包含]->变压器",
            [(0.9, "变压器 - 主设备")],
        )

        self.assertEqual(direction, "forward")

    def test_get_path_direction_rejects_unrelated_path(self):
        with self.assertRaises(ValueError):
            get_path_direction("设备-[包含]->部件", [(0.9, "变压器")])

    def test_query_path_returns_empty_without_querying_database(self):
        with patch(f"{TOG_MODULE}.query_new_neo4j") as query_neo4j:
            self.assertEqual(query_path("", "自定义主题"), ([], [], [], []))
        query_neo4j.assert_not_called()

    @patch(f"{GENERAL_MODULE}.connect_to_db")
    def test_public_theme_uses_database_label_and_creator(self, connect_to_db):
        connection = MagicMock()
        cursor = connection.cursor.return_value.__enter__.return_value
        cursor.fetchone.side_effect = [
            None,
            {
                "topic_permission": "public",
                "create_id": "6000001",
                "theme_label": "shebeijianxiu_6000001",
            },
        ]
        connect_to_db.return_value = connection

        result = resolve_theme_label_with_permission("6000002", "设备检修")

        self.assertEqual(
            result,
            ("shebeijianxiu", "shebeijianxiu_6000001", "6000001"),
        )
        connection.close.assert_called_once_with()

    @patch(
        "vue_api.kdzn_hciqa.engine_dependencies.kdzn_graph_qa_engine.find_general",
        return_value=[],
    )
    def test_engine_passes_session_id_to_general_query(self, find_general):
        engine = object.__new__(kdzn_qa)
        engine.embedd = object()
        engine.get_embedding_client = MagicMock(return_value=object())

        engine.safe_find_general(
            "6000701",
            object(),
            "重写问题",
            "文件甲",
            "设备检修",
            "设备",
            "处理方法",
            True,
            session_id="qid-1",
        )

        self.assertEqual(find_general.call_args.kwargs["session_id"], "qid-1")


if __name__ == "__main__":
    unittest.main()
