import unittest
from types import SimpleNamespace

from vue_api.kdzn_hciqa.engine_dependencies.graph_rule_queries.graph_query_utils import (
    get_chinese_properties,
    han2pinyin_concat,
    normalize_rule_paths,
    record_payload,
    remove_substrings,
)


class GraphQueryUtilsTests(unittest.TestCase):
    def test_han2pinyin_concat_normalizes_supported_characters(self):
        self.assertEqual(han2pinyin_concat("轨交 QA-01"), "guijiaoqa01")

    def test_normalize_rule_paths_accepts_empty_scalar_and_list(self):
        self.assertEqual(normalize_rule_paths(None), [])
        self.assertEqual(normalize_rule_paths("MATCH p RETURN p"), ["MATCH p RETURN p"])
        self.assertEqual(normalize_rule_paths(["q1", "q2"]), ["q1", "q2"])

    def test_record_payload_supports_record_and_mapping_shapes(self):
        payload = {"RIName": "变压器"}
        self.assertIs(record_payload([payload]), payload)
        self.assertIs(record_payload(payload), payload)

    def test_remove_substrings_keeps_only_maximal_paths(self):
        self.assertEqual(
            remove_substrings(["A-B", "A-B-C", "X-Y"]),
            ["A-B-C", "X-Y"],
        )

    def test_get_chinese_properties_keeps_chinese_keys_and_requirement(self):
        node = SimpleNamespace(
            _properties={"name": "设备", "requirement": "停电", "检查项": "声音"}
        )
        self.assertEqual(
            get_chinese_properties(node),
            {"requirement": "停电", "检查项": "声音"},
        )


if __name__ == "__main__":
    unittest.main()
