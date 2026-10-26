import unittest
from unittest.mock import Mock, patch

from vue_api.common.neo4j_client import (
    create_neo4j_driver,
    graph_config_key,
    query_neo4j,
    query_new_neo4j,
)


class FakeSession:
    def __init__(self, records):
        self.records = records
        self.calls = []

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc, traceback):
        return False

    def run(self, query, parameters):
        self.calls.append((query, parameters))
        return iter(self.records)


class Neo4jClientTests(unittest.TestCase):
    def test_graph_kind_mapping(self):
        self.assertEqual(graph_config_key("kdzn"), "kdzn")
        self.assertEqual(graph_config_key("jiapu"), "default")
        self.assertEqual(graph_config_key(""), "new_kdzn")

    def test_driver_uses_selected_configuration(self):
        config = {
            "kdzn": {"uri": "bolt://track", "username": "neo", "password": "secret"},
        }
        with patch(
            "vue_api.common.neo4j_client.load_neo4j_config",
            return_value=config,
        ), patch("vue_api.common.neo4j_client.GraphDatabase.driver") as driver:
            create_neo4j_driver("kdzn")

        driver.assert_called_once_with("bolt://track", auth=("neo", "secret"))

    def test_query_closes_driver_and_passes_parameters(self):
        session = FakeSession([{"name": "node"}])
        driver = Mock()
        driver.session.return_value = session
        with patch(
            "vue_api.common.neo4j_client.create_neo4j_driver",
            return_value=driver,
        ):
            records = query_new_neo4j(
                "MATCH (n {name: $name}) RETURN n",
                parameters={"name": "node"},
                timeout=12,
                kg="kdzn",
            )

        self.assertEqual(records, [{"name": "node"}])
        self.assertEqual(session.calls[0][1], {"name": "node"})
        self.assertEqual(session.calls[0][0].timeout, 12)
        driver.close.assert_called_once()

    def test_legacy_query_passes_cypher_as_apoc_parameter(self):
        session = FakeSession([{"value": {"name": "O'Reilly"}}])
        driver = Mock()
        driver.session.return_value = session
        statement = "RETURN \"O'Reilly\" AS name"
        with patch(
            "vue_api.common.neo4j_client.create_neo4j_driver",
            return_value=driver,
        ):
            records = query_neo4j(
                statement,
                timeout=8,
                kg="kdzn",
                parameters={"name": "O'Reilly"},
            )

        self.assertEqual(len(records), 1)
        query, parameters = session.calls[0]
        self.assertNotIn(statement, query.text)
        self.assertEqual(parameters["statement"], statement)
        self.assertEqual(parameters["query_parameters"], {"name": "O'Reilly"})
        self.assertEqual(parameters["timeout_ms"], 8000)
        driver.close.assert_called_once()


if __name__ == "__main__":
    unittest.main()
