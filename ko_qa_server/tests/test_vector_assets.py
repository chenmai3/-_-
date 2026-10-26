import tempfile
import unittest
from pathlib import Path

import faiss

from vue_api.common.vector_assets import (
    copy_compatible_vector_store,
    inspect_vector_store,
    install_staged_vector_store,
)


class VectorAssetTests(unittest.TestCase):
    @staticmethod
    def create_store(path: Path, dimension: int):
        path.mkdir(parents=True)
        faiss.write_index(faiss.IndexFlatL2(dimension), str(path / "index.faiss"))
        (path / "index.pkl").write_bytes(b"test")

    def test_inspect_reads_faiss_dimension(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            path = Path(temp_dir) / "store"
            self.create_store(path, 1024)

            status = inspect_vector_store(path)

            self.assertTrue(status.complete)
            self.assertTrue(status.compatible)
            self.assertEqual(status.dimension, 1024)
            self.assertEqual(status.document_count, 0)

    def test_copy_rejects_incompatible_dimension(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            source = Path(temp_dir) / "source"
            self.create_store(source, 1536)

            with self.assertRaisesRegex(ValueError, "incompatible vector dimension"):
                copy_compatible_vector_store(source, Path(temp_dir) / "destination")

    def test_copy_preserves_auxiliary_assets(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            source = Path(temp_dir) / "source"
            destination = Path(temp_dir) / "destination"
            self.create_store(source, 1024)
            (source / "index").mkdir()
            (source / "index" / "segment").write_text("keyword-index", encoding="utf-8")

            status = copy_compatible_vector_store(source, destination)

            self.assertTrue(status.compatible)
            self.assertTrue((destination / "index" / "segment").is_file())

    def test_install_staged_store_requires_keyword_index(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            staged = Path(temp_dir) / "staged"
            self.create_store(staged, 1024)

            with self.assertRaisesRegex(ValueError, "keyword index is missing"):
                install_staged_vector_store(staged, Path(temp_dir) / "destination")


if __name__ == "__main__":
    unittest.main()
