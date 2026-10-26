import pickle
import shutil
import tempfile
import time
from pathlib import Path

import faiss
import numpy as np
from langchain_community.vectorstores import FAISS
from langchain_core.documents import Document
from pydantic.v1 import BaseModel

from ..embedding_service import save_faiss_local_safe
from ...shared import load_config


def has_faiss_store(path):
    path = Path(path)
    return (path / "index.faiss").is_file() and (path / "index.pkl").is_file()


class _CompatibleDocument(Document):
    def __setstate__(self, state):
        if "__pydantic_fields_set__" in state and issubclass(Document, BaseModel):
            state = {
                "__dict__": state["__dict__"],
                "__fields_set__": state["__pydantic_fields_set__"],
                "__private_attribute_values__": state.get("__pydantic_private__") or {},
            }
        super().__setstate__(state)


class _CompatibleUnpickler(pickle.Unpickler):
    def find_class(self, module, name):
        if module == "langchain_core.documents.base" and name == "Document":
            return _CompatibleDocument
        return super().find_class(module, name)


def _load_legacy_faiss_store(path, embedding):
    with (path / "index.pkl").open("rb") as index_file:
        docstore, index_to_docstore_id = _CompatibleUnpickler(index_file).load()
    index = faiss.read_index(str(path / "index.faiss"))
    return FAISS(embedding, index, docstore, index_to_docstore_id)


def load_faiss_store(path, embedding):
    path = Path(path)
    def load_from(load_path):
        try:
            return FAISS.load_local(
                str(load_path), embeddings=embedding, allow_dangerous_deserialization=True
            )
        except KeyError as exc:
            if exc.args != ("__fields_set__",):
                raise
            return _load_legacy_faiss_store(load_path, embedding)

    if str(path).isascii():
        return load_from(path)

    with tempfile.TemporaryDirectory(prefix="faiss_load_") as temp_dir:
        for name in ("index.faiss", "index.pkl"):
            shutil.copy2(path / name, Path(temp_dir) / name)
        return load_from(Path(temp_dir))


def ensure_rule_entity_vector_store(path, entities, embedding):
    path = Path(path)
    if has_faiss_store(path):
        return True

    texts = []
    seen = set()
    for item in entities or []:
        text = str(item).strip()
        if text and text not in seen:
            texts.append(text)
            seen.add(text)
    if not texts:
        print(f"规则实体为空，无法生成向量库: {path}")
        return False

    try:
        path.mkdir(parents=True, exist_ok=True)
        vector_store = FAISS.from_texts(texts=texts, embedding=embedding)
        save_faiss_local_safe(vector_store, path)
        print(f"规则实体向量库已补建: {path}, 文本数: {len(texts)}")
        return True
    except Exception as exc:
        print(f"规则实体向量库补建失败: {path}, error={exc}")
        return False


def get_best_match(query, path, embedding):
    started_at = time.perf_counter()
    path = Path(path)
    print("向量库路径:", path)
    print("检索查询:", query)
    if not has_faiss_store(path):
        print(f"向量库索引不存在，跳过本地 FAISS 检索: {path}")
        return None, None

    try:
        vector_store = load_faiss_store(path, embedding)
        results = vector_store.similarity_search_with_score(query, k=1)
    except Exception as exc:
        print(f"向量库读取/检索失败: {path}, error={exc}")
        return None, None
    if not results:
        return None, None

    document, distance = results[0]
    try:
        score = 1.0 - float(distance)
    except (TypeError, ValueError):
        score = None
    print("匹配内容:", document.page_content)
    print("匹配分数:", score)
    print("耗时(s):", time.perf_counter() - started_at)
    return score, document.page_content


def get_top_matches(query, path, embedding, limit=3, min_score=0.1):
    started_at = time.perf_counter()
    path = Path(path)
    print("向量库路径:", path)
    print("检索查询:", query)
    if not has_faiss_store(path):
        print(f"向量库索引不存在，跳过本地 FAISS 检索: {path}")
        return []

    try:
        vector_store = load_faiss_store(path, embedding)
        results = vector_store.similarity_search_with_score(query, k=limit)
    except Exception as exc:
        print(f"检索过程中发生错误: {exc}")
        return []

    parsed_results = []
    for document, distance in results:
        try:
            score = 1.0 - float(distance)
        except (TypeError, ValueError):
            score = 0.0
        if score > min_score:
            parsed_results.append((score, document.page_content))
    parsed_results.sort(key=lambda item: item[0], reverse=True)
    print("耗时(s):", time.perf_counter() - started_at)
    return parsed_results[:limit]


def get_best_rule_match(query, candidates, model_client):
    candidates = list(candidates or [])
    if not candidates:
        return None, None

    texts = [query] + candidates
    embeddings = []
    model_name = load_config()["embedding_models"]["embedding_model_name"]
    for start in range(0, len(texts), 10):
        response = model_client.embeddings.create(model=model_name, input=texts[start:start + 10])
        embeddings.extend(item.embedding for item in response.data)
    if len(embeddings) != len(texts):
        raise RuntimeError(f"嵌入返回数量不一致: expected={len(texts)}, actual={len(embeddings)}")

    query_vector = np.asarray(embeddings[0])
    query_norm = np.linalg.norm(query_vector)
    best_score = -1.0
    best_candidate = None
    for candidate, vector in zip(candidates, embeddings[1:]):
        candidate_vector = np.asarray(vector)
        denominator = query_norm * np.linalg.norm(candidate_vector)
        score = float(np.dot(query_vector, candidate_vector) / denominator) if denominator else -1.0
        if score > best_score:
            best_score = score
            best_candidate = candidate
    return best_score, best_candidate


def find_most_similar(query, candidates, model_client, embedding_model_name):
    candidates = list(candidates or [])
    if not candidates:
        return None, None

    response = model_client.embeddings.create(
        model=embedding_model_name,
        input=[query] + candidates,
    )
    embeddings = [np.asarray(item.embedding) for item in response.data]
    if len(embeddings) != len(candidates) + 1:
        raise RuntimeError(
            f"嵌入返回数量不一致: expected={len(candidates) + 1}, actual={len(embeddings)}"
        )

    query_vector = embeddings[0]
    similarities = []
    for vector in embeddings[1:]:
        denominator = np.linalg.norm(query_vector) * np.linalg.norm(vector)
        similarities.append(float(np.dot(query_vector, vector) / denominator) if denominator else -1.0)
    best_index = int(np.argmax(similarities))
    return candidates[best_index], similarities[best_index]
