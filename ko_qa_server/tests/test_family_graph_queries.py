import unittest
from unittest.mock import patch

from vue_api.kdzn_hciqa.engine_dependencies.graph_rule_queries.family_graph_queries import (
    FamilyRelationStateStore,
    extract_person_desc_snippet,
    extract_valid_zibei_strict,
    query_entity_info,
)
from vue_api.kdzn_hciqa.engine_dependencies.kdzn_graph_qa_engine import kdzn_qa


class FamilyGraphQueryTests(unittest.TestCase):
    @patch(
        "vue_api.kdzn_hciqa.engine_dependencies.graph_rule_queries."
        "family_graph_queries.query_new_neo4j"
    )
    def test_entity_info_uses_parameterized_family_query(self, query):
        query.return_value = [{"n": {"name": "韦述", "zibei": "述"}}]

        result = query_entity_info('韦述" OR 1=1')

        self.assertIn("name: 韦述", result)
        cypher = query.call_args.args[0]
        self.assertIn("$entityname", cypher)
        self.assertNotIn('韦述" OR 1=1', cypher)
        self.assertEqual(
            query.call_args.kwargs["parameters"],
            {"entityname": '韦述" OR 1=1'},
        )
        self.assertEqual(query.call_args.kwargs["kg"], "jiapu")

    def test_entity_info_reports_missing_person(self):
        with patch(
            "vue_api.kdzn_hciqa.engine_dependencies.graph_rule_queries."
            "family_graph_queries.query_new_neo4j",
            return_value=[],
        ):
            self.assertEqual(query_entity_info("未知人物"), "在图谱中未查询到实体：未知人物")

    def test_generation_marker_accepts_only_single_chinese_character(self):
        records = [
            {"ZIBEI": "12"},
            {"ZIBEI": "不详"},
            {"ZIBEI": "述公"},
            {"ZIBEI": "述"},
        ]
        self.assertEqual(extract_valid_zibei_strict(records), "述")

    def test_person_description_snippet_has_fallback(self):
        self.assertEqual(extract_person_desc_snippet("姓名: 韦述, 描述: 唐代人物"), "唐代人物")
        self.assertEqual(extract_person_desc_snippet("姓名: 韦述", "未知"), "未知")

    def test_relation_states_are_isolated_by_session(self):
        store = FamilyRelationStateStore()
        first = store.get("conversation-1")
        first.people_list_1.append("人物甲")
        first.zibei_1 = "甲"

        second = store.get("conversation-2")

        self.assertEqual(second.people_list_1, [])
        self.assertEqual(second.zibei_1, "")
        self.assertIs(first, store.get("conversation-1"))

    def test_expired_relation_state_is_rebuilt(self):
        store = FamilyRelationStateStore(ttl_seconds=1)
        original = store.get("expired")
        original.updated_at -= 2

        self.assertIsNot(original, store.get("expired"))

    @patch(
        "vue_api.kdzn_hciqa.engine_dependencies.kdzn_graph_qa_engine."
        "find_kograph_zibei",
        return_value=([], [], [], [], "", [], []),
    )
    def test_engine_passes_session_id_to_family_relation_query(self, find_relation):
        engine = object.__new__(kdzn_qa)
        engine.embedd = object()

        engine.safe_find_kograph_zibei("甲", "乙", "", "", "", "", session_id="qid-1")

        self.assertEqual(find_relation.call_args.kwargs["session_id"], "qid-1")


if __name__ == "__main__":
    unittest.main()
