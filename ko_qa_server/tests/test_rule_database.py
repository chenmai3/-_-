import unittest
from unittest.mock import Mock, patch

from vue_api.rule_construct.rule_database import insert_new_data


class FakeCursor:
    lastrowid = 321

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc, traceback):
        return False

    def execute(self, query, parameters):
        return None

    def fetchone(self):
        return (
            321,
            "农业QA",
            "nongyeqa_1",
            "生长期查询",
            "MATCH (n:`nongyeqa_1`) RETURN n.name AS RIName",
        )


class RuleDatabaseTests(unittest.TestCase):
    def test_insert_builds_vector_store_from_persisted_rule(self):
        connection = Mock()
        connection.cursor.return_value = FakeCursor()
        data = [None, "场景", "生长期查询", "MATCH p RETURN p", "MATCH n RETURN n", "", ""]

        with patch(
            "vue_api.rule_construct.rule_database.build_rule_entity_vector_store"
        ) as build_store:
            result = insert_new_data(
                connection,
                data,
                "nongyeqa_1",
                "场景",
                "农业QA",
            )

        self.assertTrue(result)
        build_store.assert_called_once_with({
            "rid": 321,
            "theme_name": "农业QA",
            "theme_label": "nongyeqa_1",
            "rulename": "生长期查询",
            "getin4simi": "MATCH (n:`nongyeqa_1`) RETURN n.name AS RIName",
        })
        connection.commit.assert_called_once()


if __name__ == "__main__":
    unittest.main()
