import os
import unittest
from types import SimpleNamespace
from unittest.mock import patch

from vue_api.kdzn_hciqa.engine_dependencies.embedding_service import (
    QwenEmbeddings,
)
from vue_api.kdzn_hciqa.engine_dependencies.rule_vector_builder import (
    collect_rule_entity_texts,
    load_rule_vector_rows,
    normalize_rule_entry_query,
    rule_record_payload,
)


class Neo4jLikeRecord(tuple):
    def data(self):
        return {"R1Name": "部件", "R2Name": "周期", "RIName": "项目"}


class RuleVectorBuilderTests(unittest.TestCase):
    def test_rule_table_name_rejects_sql_fragments(self):
        with patch(
            "vue_api.kdzn_hciqa.engine_dependencies."
            "rule_vector_builder.pymysql.connect"
        ) as connect:
            with self.assertRaises(ValueError):
                load_rule_vector_rows(
                    "ko_kdzn_rule_construct; DROP TABLE rules"
                )

        connect.assert_not_called()

    def test_embedding_retries_rate_limit_errors(self):
        embedding = QwenEmbeddings.__new__(QwenEmbeddings)
        embedding.model_name = "test-model"
        calls = 0

        class RateLimit(Exception):
            status_code = 429

        def create(**kwargs):
            nonlocal calls
            calls += 1
            if calls == 1:
                raise RateLimit("limited")
            return SimpleNamespace(data=[SimpleNamespace(embedding=[1.0])])

        embedding.client = SimpleNamespace(embeddings=SimpleNamespace(create=create))
        with patch.dict(os.environ, {"KO_QA_EMBEDDING_RETRY_BASE": "0"}), patch("time.sleep"):
            vectors = embedding.embed_query("query")

        self.assertEqual(vectors, [1.0])
        self.assertEqual(calls, 2)

    def test_embedding_documents_are_split_into_api_sized_batches(self):
        embedding = QwenEmbeddings.__new__(QwenEmbeddings)
        embedding.model_name = "test-model"
        calls = []

        def create(**kwargs):
            calls.append(kwargs["input"])
            return SimpleNamespace(
                data=[SimpleNamespace(embedding=[float(value)]) for value in kwargs["input"]]
            )

        embedding.client = SimpleNamespace(embeddings=SimpleNamespace(create=create))

        vectors = embedding.embed_documents(list(range(26)))

        self.assertEqual([len(batch) for batch in calls], [10, 10, 6])
        self.assertEqual(len(vectors), 26)

    def test_record_data_takes_precedence_over_tuple_shape(self):
        record = Neo4jLikeRecord(("first positional value",))

        self.assertEqual(rule_record_payload(record)["RIName"], "项目")

    def test_collects_and_deduplicates_rule_entity_text(self):
        row = {
            "theme_name": "轨交诊断",
            "getin4simi": "MATCH (n) RETURN n",
        }
        record = Neo4jLikeRecord(("first positional value",))

        with patch(
            "vue_api.kdzn_hciqa.engine_dependencies.rule_vector_builder.query_new_neo4j",
            return_value=[record, record],
        ):
            self.assertEqual(collect_rule_entity_texts(row), ["部件周期项目"])

    def test_normalizes_single_character_theme_label_typo(self):
        row = {
            "theme_label": "nongzuowu_6000677",
            "getin4simi": (
                "MATCH (f:`nongzuowu_600677`)-[:`has`]->"
                "(n:`nongzuowu_6000677`) RETURN n"
            ),
        }

        query = normalize_rule_entry_query(row)

        self.assertNotIn("nongzuowu_600677`", query)
        self.assertEqual(query.count("nongzuowu_6000677"), 2)

    def test_does_not_replace_unrelated_query_labels(self):
        row = {
            "theme_label": "theme_1000",
            "getin4simi": "MATCH (a:`another_1000`)-[:`has`]->(n:`theme_1000`) RETURN n",
        }

        self.assertEqual(normalize_rule_entry_query(row), row["getin4simi"])


if __name__ == "__main__":
    unittest.main()
