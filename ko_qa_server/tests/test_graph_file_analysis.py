import unittest

from vue_api.graph_construct.file_analysis import build_normal_file_result_rows


class GraphFileAnalysisTests(unittest.TestCase):
    def test_build_rows_keeps_valid_triples_and_counts_invalid_rows(self):
        rows, invalid = build_normal_file_result_rows(
            "sample.txt",
            [["甲", "父亲", "乙"], ["缺失", "关系"], ["丙", "母亲", "丁"]],
        )

        self.assertEqual(rows[0], ["根节点", "类型", "头实体", "关系", "尾实体"])
        self.assertEqual(rows[1], ["sample.txt", "文件", "甲", "父亲", "乙"])
        self.assertEqual(rows[2], ["sample.txt", "文件", "丙", "母亲", "丁"])
        self.assertEqual(invalid, 1)


if __name__ == "__main__":
    unittest.main()
