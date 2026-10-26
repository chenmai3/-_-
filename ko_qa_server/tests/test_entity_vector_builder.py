import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock, patch

from vue_api.kdzn_hciqa.engine_dependencies.entity_vector_builder import (
    build_entry_entity_vector_store,
    normalize_entity_names,
)


class EntityVectorBuilderTests(unittest.TestCase):
    def test_entity_names_are_trimmed_and_deduplicated(self):
        self.assertEqual(
            normalize_entity_names([" 萌芽期 ", "", "萌芽期", None, "开花期"]),
            ["萌芽期", "开花期"],
        )

    def test_empty_entity_list_does_not_initialize_embedding(self):
        with tempfile.TemporaryDirectory() as temp_dir, patch(
            "vue_api.kdzn_hciqa.engine_dependencies."
            "entity_vector_builder.resolve_entity_vector_path",
            return_value=Path(temp_dir) / "empty",
        ), patch(
            "vue_api.kdzn_hciqa.engine_dependencies."
            "entity_vector_builder.QwenEmbeddings"
        ) as embedding:
            result = build_entry_entity_vector_store(
                "农业QA",
                "nongyeqa_1",
                "生长周期",
                [],
            )

        self.assertEqual(result["status"], "empty")
        self.assertEqual(result["documents"], 0)
        embedding.assert_not_called()

    def test_new_store_indexes_deduplicated_documents(self):
        indexer = Mock()
        indexer.index_docs_qwen.return_value = 2
        embedding = SimpleNamespace(model_name="embedding-test")
        with tempfile.TemporaryDirectory() as temp_dir, patch(
            "vue_api.kdzn_hciqa.engine_dependencies."
            "entity_vector_builder.resolve_entity_vector_path",
            return_value=Path(temp_dir) / "entities",
        ), patch(
            "vue_api.kdzn_hciqa.engine_dependencies."
            "entity_vector_builder.probe_embedding_dimension",
            return_value=3,
        ):
            result = build_entry_entity_vector_store(
                "农业QA",
                "nongyeqa_1",
                "生长周期",
                ["萌芽期", "萌芽期", "开花期"],
                embedding=embedding,
                indexer=indexer,
                model_client=object(),
            )

        call = indexer.index_docs_qwen.call_args
        self.assertEqual(
            [document.page_content for document in call.kwargs["docs"]],
            ["萌芽期", "开花期"],
        )
        self.assertEqual(call.kwargs["model_name"], "embedding-test")
        self.assertEqual(result["documents"], 2)
        self.assertEqual(result["end_id"], 2)


if __name__ == "__main__":
    unittest.main()
