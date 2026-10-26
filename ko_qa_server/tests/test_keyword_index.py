import pickle
import tempfile
import unittest
import gc
from pathlib import Path

from langchain_community.docstore.in_memory import InMemoryDocstore
from langchain_core.documents import Document
from whoosh.index import open_dir
from whoosh.qparser import QueryParser

from vue_api.common.keyword_index import rebuild_keyword_index


class KeywordIndexTests(unittest.TestCase):
    def test_rebuilds_keyword_index_from_faiss_docstore(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            document = Document(
                page_content="向量库本地构建流程包括文本切分和嵌入生成",
                metadata={"名称": "流程文档", "id": "0"},
            )
            payload = (InMemoryDocstore({"0": document}), {0: "0"})
            with open(root / "index.pkl", "wb") as file:
                pickle.dump(payload, file)

            count = rebuild_keyword_index(root)

            index = open_dir(str(root / "index"))
            try:
                with index.searcher() as searcher:
                    results = searcher.search(QueryParser("content", index.schema).parse("向量库"))
                    result_count = len(results)
                    result_title = results[0]["title"]
                    del results
                del searcher
            finally:
                index.close()
                del index
                gc.collect()
            self.assertEqual(count, 1)
            self.assertEqual(result_count, 1)
            self.assertEqual(result_title, "流程文档")


if __name__ == "__main__":
    unittest.main()
