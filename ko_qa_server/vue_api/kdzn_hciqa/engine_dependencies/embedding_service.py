import os
import shutil
import tempfile
import time
from pathlib import Path
from typing import List

import yaml
from langchain_core.embeddings import Embeddings
from openai import OpenAI, OpenAIError

from ..shared import CONFIG_PATH


with CONFIG_PATH.open(encoding="utf-8") as config_file:
    cfg = yaml.safe_load(config_file)


class EmbeddingServiceUnavailable(RuntimeError):
    pass


def explain_embedding_error(exc: Exception) -> str:
    body = getattr(exc, "body", None)
    message = str(exc)
    if isinstance(body, dict):
        error = body.get("error") or {}
        code = error.get("code") or error.get("type")
        detail = error.get("message") or message
        if code == "Arrearage" or "overdue-payment" in detail:
            return (
                "Embedding 服务调用失败：阿里百炼/DashScope 账号欠费或不可用。"
                "请恢复账号状态，或在私有配置中更换 embedding_models 后重试。"
            )
        return f"Embedding 服务调用失败：{code or 'unknown'} - {detail}"
    if "Arrearage" in message or "overdue-payment" in message:
        return (
            "Embedding 服务调用失败：阿里百炼/DashScope 账号欠费或不可用。"
            "请恢复账号状态，或在私有配置中更换 embedding_models 后重试。"
        )
    return f"Embedding 服务调用失败：{message}"


def probe_embedding_dimension(embeddings) -> int:
    try:
        return len(embeddings.embed_query("hello world"))
    except OpenAIError as exc:
        raise EmbeddingServiceUnavailable(explain_embedding_error(exc)) from exc
    except Exception as exc:
        raise EmbeddingServiceUnavailable(explain_embedding_error(exc)) from exc


def ensure_vector_store_dir(path) -> Path:
    vector_path = Path(path)
    vector_path.mkdir(parents=True, exist_ok=True)
    if not vector_path.is_dir():
        raise RuntimeError(f"向量库目录创建失败: {vector_path}")
    return vector_path


def save_faiss_local_safe(vector_stores, save_path) -> Path:
    save_path = ensure_vector_store_dir(save_path)
    try:
        vector_stores.save_local(str(save_path))
    except RuntimeError as exc:
        print(f"[WARN] save_local direct failed, fallback to temp ascii path: {exc}")
        with tempfile.TemporaryDirectory(prefix="faiss_store_") as tmp_dir:
            tmp_path = Path(tmp_dir)
            vector_stores.save_local(str(tmp_path))
            for name in ("index.faiss", "index.pkl"):
                shutil.copy2(tmp_path / name, save_path / name)

    missing_files = [
        name
        for name in ("index.faiss", "index.pkl")
        if not (save_path / name).is_file()
    ]
    if missing_files:
        raise RuntimeError(
            f"FAISS vector store save incomplete: {save_path}, "
            f"missing={missing_files}"
        )
    return save_path


class QwenEmbeddings(Embeddings):
    def __init__(self):
        embedding_config = cfg["embedding_models"]
        self.client = OpenAI(
            api_key=embedding_config["api_key"],
            base_url=embedding_config["base_url"],
            timeout=float(os.getenv("KO_QA_EMBEDDING_TIMEOUT", "60")),
            max_retries=0,
        )
        self.model_name = embedding_config["embedding_model_name"]

    def _create_embeddings(self, texts):
        max_retries = int(os.getenv("KO_QA_EMBEDDING_MAX_RETRIES", "6"))
        retry_base = float(os.getenv("KO_QA_EMBEDDING_RETRY_BASE", "2"))
        for attempt in range(max_retries + 1):
            try:
                return self.client.embeddings.create(
                    model=self.model_name,
                    input=texts,
                    dimensions=1024,
                    encoding_format="float",
                )
            except Exception as exc:
                status_code = getattr(exc, "status_code", None)
                connection_error = type(exc).__name__ in {
                    "APIConnectionError",
                    "APITimeoutError",
                    "ConnectError",
                    "ReadTimeout",
                }
                retryable = (
                    status_code in {408, 409, 429, 500, 502, 503, 504}
                    or connection_error
                )
                if not retryable or attempt >= max_retries:
                    raise
                delay = min(60.0, retry_base * (2**attempt))
                print(
                    f"[Embedding Retry] status={status_code or 'connection'}, "
                    f"attempt={attempt + 1}/{max_retries}, delay={delay:.1f}s"
                )
                time.sleep(delay)

    def embed_documents(self, texts: List[str]) -> List[List[float]]:
        vectors = []
        batch_delay = float(
            os.getenv("KO_QA_EMBEDDING_BATCH_DELAY", "0.2")
        )
        for start in range(0, len(texts), 10):
            batch = texts[start : start + 10]
            response = self._create_embeddings(batch)
            vectors.extend(item.embedding for item in response.data)
            if batch_delay > 0 and start + 10 < len(texts):
                time.sleep(batch_delay)
        return vectors

    def embed_query(self, text: str) -> List[float]:
        response = self._create_embeddings([text])
        return response.data[0].embedding
