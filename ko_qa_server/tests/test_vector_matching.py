import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

from vue_api.kdzn_hciqa.engine_dependencies.graph_rule_queries.vector_matching import (
    _CompatibleDocument,
    find_most_similar,
    get_best_match,
    get_best_rule_match,
)


class FakeEmbeddings:
    def __init__(self):
        self.batch_sizes = []

    def create(self, model, input):
        self.batch_sizes.append(len(input))
        vectors = {
            "query": [1.0, 0.0],
            "near": [0.9, 0.1],
            "far": [0.0, 1.0],
        }
        return SimpleNamespace(
            data=[SimpleNamespace(embedding=vectors.get(text, [0.5, 0.5])) for text in input]
        )


class VectorMatchingTests(unittest.TestCase):
    def test_legacy_document_accepts_pydantic_v2_state(self):
        document = _CompatibleDocument.__new__(_CompatibleDocument)
        document.__setstate__(
            {
                "__dict__": {"page_content": "sample", "metadata": {"id": "1"}},
                "__pydantic_fields_set__": {"page_content", "metadata"},
                "__pydantic_extra__": None,
                "__pydantic_private__": None,
            }
        )

        self.assertEqual(document.page_content, "sample")
        self.assertEqual(document.metadata, {"id": "1"})

    def test_rule_match_skips_embedding_for_empty_candidates(self):
        client = SimpleNamespace(embeddings=FakeEmbeddings())

        self.assertEqual(get_best_rule_match("query", [], client), (None, None))
        self.assertEqual(client.embeddings.batch_sizes, [])

    @patch(
        "vue_api.kdzn_hciqa.engine_dependencies.graph_rule_queries."
        "vector_matching.load_config",
        return_value={"embedding_models": {"embedding_model_name": "embedding-test"}},
    )
    def test_rule_match_batches_requests_and_returns_best_candidate(self, _config):
        embeddings = FakeEmbeddings()
        client = SimpleNamespace(embeddings=embeddings)
        candidates = ["far"] * 10 + ["near"]

        score, candidate = get_best_rule_match("query", candidates, client)

        self.assertEqual(embeddings.batch_sizes, [10, 2])
        self.assertEqual(candidate, "near")
        self.assertGreater(score, 0.9)

    def test_missing_faiss_store_returns_empty_match(self):
        with tempfile.TemporaryDirectory() as directory:
            self.assertEqual(get_best_match("query", Path(directory), object()), (None, None))

    def test_find_most_similar_handles_empty_candidates(self):
        client = SimpleNamespace(embeddings=FakeEmbeddings())
        self.assertEqual(find_most_similar("query", [], client, "embedding-test"), (None, None))


if __name__ == "__main__":
    unittest.main()
