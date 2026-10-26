import tempfile
import unittest
from pathlib import Path

from vue_api.kdzn_hciqa.engine_dependencies.embedding_service import (
    EmbeddingServiceUnavailable,
    QwenEmbeddings,
    ensure_vector_store_dir,
    explain_embedding_error,
    probe_embedding_dimension,
    save_faiss_local_safe,
)


class EmbeddingServiceTests(unittest.TestCase):
    def test_legacy_chatbot_exports_canonical_embedding_class(self):
        from vue_api.kdzn_hciqa.engine_dependencies.knowledge_base_chatbot import (
            QwenEmbeddings as LegacyQwenEmbeddings,
        )

        self.assertIs(LegacyQwenEmbeddings, QwenEmbeddings)
        self.assertEqual(
            LegacyQwenEmbeddings.__module__,
            "vue_api.kdzn_hciqa.engine_dependencies.embedding_service",
        )

    def test_arrearage_error_has_actionable_message(self):
        error = RuntimeError("overdue-payment")
        error.body = {
            "error": {
                "code": "Arrearage",
                "message": "Access denied: overdue-payment",
            }
        }

        message = explain_embedding_error(error)

        self.assertIn("账号欠费", message)
        self.assertIn("私有配置", message)

    def test_probe_wraps_embedding_failures(self):
        class BrokenEmbedding:
            def embed_query(self, _text):
                raise RuntimeError("offline")

        with self.assertRaises(EmbeddingServiceUnavailable) as raised:
            probe_embedding_dimension(BrokenEmbedding())

        self.assertIn("offline", str(raised.exception))

    def test_ensure_vector_store_dir_creates_nested_directory(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            destination = Path(temp_dir) / "nested" / "vector-store"

            result = ensure_vector_store_dir(destination)

            self.assertEqual(result, destination)
            self.assertTrue(destination.is_dir())

    def test_safe_save_falls_back_to_ascii_temp_directory(self):
        class Store:
            def __init__(self):
                self.calls = []

            def save_local(self, path):
                self.calls.append(Path(path))
                if len(self.calls) == 1:
                    raise RuntimeError("destination path is unsupported")
                target = Path(path)
                (target / "index.faiss").write_bytes(b"faiss")
                (target / "index.pkl").write_bytes(b"metadata")

        with tempfile.TemporaryDirectory() as temp_dir:
            destination = Path(temp_dir) / "向量库"
            store = Store()

            result = save_faiss_local_safe(store, destination)

            self.assertEqual(result, destination)
            self.assertEqual(len(store.calls), 2)
            self.assertTrue((destination / "index.faiss").is_file())
            self.assertTrue((destination / "index.pkl").is_file())


if __name__ == "__main__":
    unittest.main()
