import unittest
from unittest.mock import patch

from vue_api.kdzn_hciqa.engine_dependencies.graph_rule_queries.rail_graph_queries import (
    all_paths_from_entity,
    find_kdzn,
    get_yichang,
)


RAIL_MODULE = (
    "vue_api.kdzn_hciqa.engine_dependencies.graph_rule_queries.rail_graph_queries"
)


class RailGraphQueriesTests(unittest.TestCase):
    @patch(f"{RAIL_MODULE}.query_new_neo4j", return_value=[])
    def test_all_paths_from_entity_uses_parameterized_entity_name(self, query_neo4j):
        entity_name = '变压器"}) MATCH (n) RETURN n //'

        self.assertEqual(all_paths_from_entity(entity_name), ([], []))
        query, = query_neo4j.call_args.args
        self.assertNotIn(entity_name, query)
        query_neo4j.assert_called_once_with(
            query,
            parameters={"entityname": entity_name},
            kg="kdzn",
        )

    @patch(f"{RAIL_MODULE}.kdzn_file_rules_kdzn_generate", return_value={})
    def test_find_kdzn_returns_empty_result_when_scene_has_no_rules(self, _rules):
        result = find_kdzn(
            "6000701",
            "轨交诊断",
            "不存在的检查项",
            "查询实体",
            "处理方法",
            object(),
            object(),
        )

        self.assertEqual(result, ([], [], [], []))

    @patch(f"{RAIL_MODULE}.query_new_neo4j", return_value=[])
    @patch(f"{RAIL_MODULE}.get_best_match", return_value=(0.9, "变压器"))
    @patch(f"{RAIL_MODULE}.has_faiss_store", return_value=True)
    @patch(
        f"{RAIL_MODULE}.query_neo4j",
        return_value=[[{"RIName": "变压器"}]],
    )
    @patch(
        f"{RAIL_MODULE}.kdzn_file_rules_kdzn_generate",
        return_value={
            "声音异常检查": [
                {
                    "rid": 2401,
                    "rule_name": "异常现象的原因和处理办法",
                    "getIn4simi": "MATCH input",
                    "rule_path": 'MATCH (n {name: "{entityname}"}) RETURN n',
                }
            ]
        },
    )
    def test_find_kdzn_executes_rendered_rule_after_entity_match(
        self,
        _rules,
        _query_input,
        _has_store,
        _best_match,
        query_rule,
    ):
        result = find_kdzn(
            "6000701",
            "轨交诊断",
            "声音异常检查",
            "变压器发出吱吱声",
            "处理方法",
            object(),
            object(),
        )

        self.assertEqual(result, ([], [], [], []))
        query_rule.assert_called_once_with(
            'MATCH (n {name: "变压器"}) RETURN n',
            kg="kdzn",
        )

    @patch(f"{RAIL_MODULE}.query_new_neo4j", return_value=[])
    @patch(f"{RAIL_MODULE}.get_best_rule_match", side_effect=ConnectionError("offline"))
    @patch(f"{RAIL_MODULE}.get_best_match", return_value=(None, None))
    @patch(f"{RAIL_MODULE}.ensure_rule_entity_vector_store", return_value=False)
    @patch(f"{RAIL_MODULE}.has_faiss_store", return_value=False)
    @patch(
        f"{RAIL_MODULE}.query_neo4j",
        return_value=[[{"RIName": "变压器发出吱吱声"}]],
    )
    @patch(
        f"{RAIL_MODULE}.kdzn_file_rules_kdzn_generate",
        return_value={
            "声音异常检查": [
                {
                    "rid": 24,
                    "rule_name": "声音异常检查完整链路",
                    "getIn4simi": "MATCH input",
                    "rule_path": ["MATCH (wrong) RETURN wrong"],
                },
                {
                    "rid": 2401,
                    "rule_name": "异常现象的原因和处理办法",
                    "getIn4simi": "MATCH input",
                    "rule_path": ['MATCH (n {name: "{entityname}"}) RETURN n'],
                },
            ]
        },
    )
    def test_find_kdzn_uses_local_match_when_embedding_connection_fails(
        self,
        _rules,
        _query_input,
        _has_store,
        _ensure_store,
        _best_match,
        embedding_match,
        query_rule,
    ):
        result = find_kdzn(
            "6000701",
            "轨交诊断",
            "声音异常检查",
            "变压器发出吱吱声",
            "处理方法",
            object(),
            object(),
        )

        self.assertEqual(result, ([], [], [], []))
        embedding_match.assert_called_once()
        _ensure_store.assert_not_called()
        query_rule.assert_called_once_with(
            'MATCH (n {name: "变压器发出吱吱声"}) RETURN n',
            kg="kdzn",
        )

    @patch(f"{RAIL_MODULE}.AutoModel.from_pretrained")
    @patch(f"{RAIL_MODULE}.AutoTokenizer.from_pretrained")
    @patch(f"{RAIL_MODULE}.kdzn_file_rules_kdzn_generate", return_value={})
    def test_get_yichang_returns_empty_result_without_rule_indexes(
        self,
        _rules,
        _tokenizer,
        _model,
    ):
        self.assertEqual(
            get_yichang("异常声音", "处理方法", "unused-model"),
            ([], [], [], []),
        )


if __name__ == "__main__":
    unittest.main()
