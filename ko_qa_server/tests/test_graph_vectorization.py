import tempfile
import unittest
from pathlib import Path
from unittest.mock import Mock, patch

from vue_api.graph_construct.graph_data import (
    vectorize_entry_entities,
    vectorize_original_file,
)


class GraphVectorizationTests(unittest.TestCase):
    def test_original_file_uses_canonical_vectorizer(self):
        vectorizer = Mock()
        with tempfile.TemporaryDirectory() as temp_dir:
            source = Path(temp_dir) / "source.txt"
            source.write_text("content", encoding="utf-8")
            with patch(
                "vue_api.graph_construct.graph_data.find_original_file",
                return_value=source,
            ), patch(
                "vue_api.kdzn_hciqa.engine_dependencies.knowledge_base_chatbot.Chatzxl",
                return_value=vectorizer,
            ):
                result = vectorize_original_file("user-1", "农业QA", source.name)

        self.assertTrue(result)
        vectorizer.init_database.assert_called_once()
        vectorizer.update_vector_stores.assert_called_once()

    def test_entry_entities_use_canonical_vector_builder(self):
        with patch(
            "vue_api.kdzn_hciqa.engine_dependencies.entity_vector_builder.get_entity_vector",
            return_value=12,
        ) as build_entities:
            result = vectorize_entry_entities("农业QA", "nongyeqa_1", "场景", ["萌芽期"])

        self.assertEqual(result, 12)
        build_entities.assert_called_once_with("农业QA", "nongyeqa_1", "场景", ["萌芽期"])


if __name__ == "__main__":
    unittest.main()
