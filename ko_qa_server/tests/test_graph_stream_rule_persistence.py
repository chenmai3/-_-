import unittest
from contextlib import nullcontext
from unittest.mock import MagicMock, patch

from vue_api.kdzn_hciqa.qa_answer.graph_stream_answer import (
    generate_and_save_rules_after_answer,
    insert_rule_data,
)


class GraphStreamRulePersistenceTests(unittest.TestCase):
    def test_rail_answer_does_not_generate_rules_without_general_search_results(self):
        with patch(
            "vue_api.kdzn_hciqa.qa_answer.graph_stream_answer.build_rule_candidates"
        ) as build_candidates, patch(
            "vue_api.kdzn_hciqa.qa_answer.graph_stream_answer.connect_to_db"
        ) as connect:
            generate_and_save_rules_after_answer(
                "轨交诊断",
                "kedazhineng",
                ["声音异常检查"],
                {},
                {},
                [{"query": "变压器发出吱吱声应该怎么处理？", "answer": "检查连接部位。"}],
            )

        build_candidates.assert_not_called()
        connect.assert_not_called()

    def test_general_answer_still_generates_rules_from_search_results(self):
        search_results = {"场景": [object()]}
        over_flags = {"场景": [True]}
        candidates = [{"entity": "入口实体"}]
        rules = [{"rulename": "处理规则", "rule_path": ["MATCH p RETURN p"], "getIn4simi": "MATCH n RETURN n"}]
        connection = MagicMock()
        with patch(
            "vue_api.kdzn_hciqa.qa_answer.graph_stream_answer.build_rule_candidates",
            return_value=candidates,
        ) as build_candidates, patch(
            "vue_api.kdzn_hciqa.qa_answer.graph_stream_answer.generate_generalized_rule_names",
            return_value=rules,
        ) as name_rules, patch(
            "vue_api.kdzn_hciqa.qa_answer.graph_stream_answer.connect_to_db",
            return_value=connection,
        ), patch(
            "vue_api.kdzn_hciqa.qa_answer.graph_stream_answer.insert_rule_data"
        ) as insert:
            generate_and_save_rules_after_answer(
                "农业QA", "nongyeqa_1", ["场景"], search_results, over_flags, [{"query": "问题"}]
            )

        build_candidates.assert_called_once_with("农业QA", "nongyeqa_1", "场景", search_results, over_flags)
        name_rules.assert_called_once_with([{"query": "问题"}], candidates)
        insert.assert_called_once()
        connection.close.assert_called_once_with()

    def test_inserted_rule_uses_canonical_vector_builder(self):
        cursor = MagicMock()
        cursor.lastrowid = 2401
        connection = MagicMock()
        connection.cursor.return_value = nullcontext(cursor)
        data = [
            None,
            None,
            "异常处理规则",
            ["MATCH p RETURN p"],
            "MATCH input RETURN input",
            "规则路径",
            "入口路径",
        ]

        with patch(
            "vue_api.kdzn_hciqa.engine_dependencies."
            "rule_vector_builder.build_rule_entity_vector_store"
        ) as build_store:
            insert_rule_data(
                connection,
                data,
                "kedazhineng",
                "油浸式电力变压器试验",
                "轨交诊断",
            )

        connection.commit.assert_called_once_with()
        build_store.assert_called_once_with(
            {
                "rid": 2401,
                "theme_name": "轨交诊断",
                "theme_label": "kedazhineng",
                "getin4simi": "MATCH input RETURN input",
            }
        )
        self.assertEqual(cursor.execute.call_count, 1)


if __name__ == "__main__":
    unittest.main()
