import pickle
import shutil
import uuid
from pathlib import Path

import jieba
from whoosh.analysis import Token, Tokenizer
from whoosh.fields import ID, TEXT, Schema
from whoosh.index import create_in, open_dir


class JiebaTokenizer(Tokenizer):
    def __call__(self, value, **kwargs):
        if not isinstance(value, str):
            value = value.decode("utf-8")
        token = Token()
        start = 0
        for word in jieba.cut(value, cut_all=False):
            token.original = word
            token.text = word
            token.boost = 1.0
            token.startchar = value.find(word, start)
            token.endchar = token.startchar + len(word)
            token.pos = 0
            start = token.endchar
            yield token


def jieba_analyzer():
    return JiebaTokenizer()


def _load_faiss_documents(vector_store_path: Path):
    with open(vector_store_path / "index.pkl", "rb") as file:
        docstore, index_mapping = pickle.load(file)

    documents = []
    for position in sorted(index_mapping):
        document_id = index_mapping[position]
        document = docstore.search(document_id)
        if isinstance(document, str):
            continue
        documents.append((str(document_id), document))
    return documents


def rebuild_keyword_index(vector_store_path) -> int:
    vector_store_path = Path(vector_store_path)
    documents = _load_faiss_documents(vector_store_path)
    if not documents:
        raise ValueError(f"FAISS docstore is empty: {vector_store_path}")

    schema = Schema(
        title=TEXT(stored=True, analyzer=jieba_analyzer()),
        path=ID(stored=True, unique=True),
        content=TEXT(stored=True, analyzer=jieba_analyzer()),
    )
    index_path = vector_store_path / "index"
    temp_path = vector_store_path / f".index.rebuilding-{uuid.uuid4().hex}"
    backup_path = vector_store_path / f".index.legacy-{uuid.uuid4().hex}"
    temp_path.mkdir(parents=True)
    try:
        index = create_in(str(temp_path), schema)
        writer = index.writer()
        for document_id, document in documents:
            metadata = getattr(document, "metadata", {}) or {}
            content = str(getattr(document, "page_content", "") or metadata.get("content") or "")
            writer.add_document(
                title=str(metadata.get("名称") or metadata.get("source") or ""),
                path=str(metadata.get("id") or document_id),
                content=content,
            )
        writer.commit()
        index.close()
        check_index = open_dir(str(temp_path))
        try:
            if check_index.doc_count() != len(documents):
                raise RuntimeError("keyword index document count mismatch")
        finally:
            check_index.close()

        if index_path.exists():
            index_path.rename(backup_path)
        temp_path.rename(index_path)
        if backup_path.exists():
            shutil.rmtree(backup_path)
    except Exception:
        if backup_path.exists() and not index_path.exists():
            backup_path.rename(index_path)
        raise
    finally:
        if temp_path.exists():
            shutil.rmtree(temp_path)
    return len(documents)
