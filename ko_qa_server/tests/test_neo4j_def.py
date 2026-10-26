import unittest
from unittest.mock import patch

from vue_api.kdzn_hciqa.engine_dependencies.graph_rule_queries.neo4j_def import (
    KO_tupu,
    n_hop_ent,
)


MODULE = (
    "vue_api.kdzn_hciqa.engine_dependencies.graph_rule_queries.neo4j_def"
)


class Neo4jDefinitionTests(unittest.TestCase):
    @patch(f"{MODULE}.query_neo4j", return_value=[])
    def test_entity_name_is_passed_as_neo4j_parameter(self, query_neo4j):
        malicious_name = '设备"}) MATCH (n) RETURN n //'

        result = n_hop_ent(malicious_name, 1)

        self.assertEqual(result, ([], []))
        query = query_neo4j.call_args.args[0]
        self.assertNotIn(malicious_name, query)
        query_neo4j.assert_called_once_with(
            query,
            parameters={"head": malicious_name},
        )

    @patch(f"{MODULE}.query_neo4j")
    def test_invalid_hop_count_is_rejected_before_query(self, query_neo4j):
        for value in (0, 6):
            with self.subTest(value=value), self.assertRaises(ValueError):
                n_hop_ent("变压器", value)
        query_neo4j.assert_not_called()

    @patch(f"{MODULE}.n_hop_ent")
    def test_ko_tupu_keeps_one_result_group_per_keyword(self, n_hop_ent):
        n_hop_ent.side_effect = [
            (["路径甲"], [["三元组甲"]]),
            (["路径乙"], [["三元组乙"]]),
        ]

        result = KO_tupu(["实体甲", "实体乙"])

        self.assertEqual(result, [["路径甲"], ["路径乙"]])
        self.assertEqual(
            n_hop_ent.call_args_list[0].args,
            ("实体甲", 1),
        )
        self.assertEqual(
            n_hop_ent.call_args_list[1].args,
            ("实体乙", 1),
        )


if __name__ == "__main__":
    unittest.main()
