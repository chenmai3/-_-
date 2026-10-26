import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from langchain_core.documents import Document

from vue_api.common.vector_assets import inspect_vector_store
from vue_api.kdzn_hciqa.engine_dependencies.user_store_rebuilder import (
    rebuild_user_vector_store,
)


class FakeEmbedding:
    @staticmethod
    def _vector(text):
        vector = [0.0] * 1024
        vector[0] = float(len(text))
        return vector

    def embed_documents(self, texts):
        return [self._vector(text) for text in texts]

    def embed_query(self, text):
        return self._vector(text)


class UserStoreRebuilderTests(unittest.TestCase):
    def test_rebuilds_complete_store_before_installing(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            source_root = root / "uploads"
            destination_root = root / "vectors"
            source = source_root / "user-1"
            source.mkdir(parents=True)
            (source / "one.txt").write_text("first", encoding="utf-8")
            (source / "two.md").write_text("second", encoding="utf-8")

            def extract(path, reuse_extracted=False):
                return [
                    Document(
                        page_content=path.read_text(encoding="utf-8"),
                        metadata={"名称": path.name, "content": path.read_text(encoding="utf-8")},
                    )
                ]

            with patch(
                "vue_api.kdzn_hciqa.engine_dependencies.user_store_rebuilder.extract_documents_from_user_file",
                side_effect=extract,
            ):
                result = rebuild_user_vector_store(
                    "user-1",
                    source_root=source_root,
                    destination_root=destination_root,
                    embedding=FakeEmbedding(),
                )

            status = inspect_vector_store(destination_root / "user-1")
            self.assertEqual(result.status, "rebuilt")
            self.assertEqual(status.document_count, 2)
            self.assertTrue((destination_root / "user-1" / "index").is_dir())
            self.assertTrue((destination_root / "user-1" / "doc_rangs.json").is_file())


if __name__ == "__main__":
    unittest.main()
