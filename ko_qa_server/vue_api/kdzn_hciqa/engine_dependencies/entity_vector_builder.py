from pathlib import Path

import faiss
from langchain_community.docstore.in_memory import InMemoryDocstore
from langchain_community.vectorstores import FAISS
from langchain_core.documents import Document

from ..shared import (
    JIAPU_ENTITY_VECTOR_STORE,
    entity_vector_store_path,
)
from .embedding_service import (
    QwenEmbeddings,
    ensure_vector_store_dir,
    probe_embedding_dimension,
)
from .graph_rule_queries.graph_query_utils import han2pinyin_concat
from .llm_clients import llm_config


def has_faiss_store(path) -> bool:
    path = Path(path)
    return (path / "index.faiss").is_file() and (path / "index.pkl").is_file()


def normalize_entity_names(names):
    normalized = []
    seen = set()
    for value in names or []:
        if value is None:
            continue
        name = str(value).strip()
        if name and name not in seen:
            normalized.append(name)
            seen.add(name)
    return normalized


def entity_documents(names):
    return [
        Document(
            page_content=name,
            metadata={"content": name, "id": str(index)},
        )
        for index, name in enumerate(names)
    ]


def resolve_entity_vector_path(selected_main_scenario, label, scene):
    if selected_main_scenario == "家谱主题问答":
        return JIAPU_ENTITY_VECTOR_STORE
    return entity_vector_store_path(label, han2pinyin_concat(scene))


def build_entry_entity_vector_store(
    selected_main_scenario,
    label,
    scene,
    names,
    *,
    embedding=None,
    indexer=None,
    model_client=None,
):
    names = normalize_entity_names(names)
    path = ensure_vector_store_dir(
        resolve_entity_vector_path(
            selected_main_scenario,
            label,
            scene,
        )
    )
    if not names:
        return {
            "status": "empty",
            "path": str(path),
            "documents": 0,
        }

    embedding = embedding or QwenEmbeddings()
    if has_faiss_store(path):
        vector_store = FAISS.load_local(
            str(path),
            embedding,
            allow_dangerous_deserialization=True,
        )
    else:
        dimension = probe_embedding_dimension(embedding)
        vector_store = FAISS(
            embedding_function=embedding,
            index=faiss.IndexFlatL2(dimension),
            docstore=InMemoryDocstore(),
            index_to_docstore_id={},
        )

    if indexer is None:
        from .knowledge_base_chatbot import Chatzxl

        indexer = Chatzxl()
    if model_client is None:
        model_client = llm_config().embedd

    end_id = indexer.index_docs_qwen(
        vector_stores=vector_store,
        docs=entity_documents(names),
        model_client=model_client,
        model_name=embedding.model_name,
        save_path=path,
    )
    return {
        "status": "built",
        "path": str(path),
        "documents": len(names),
        "end_id": end_id,
    }


def get_entity_vector(selectedMainScenario, label, fo, names_list):
    return build_entry_entity_vector_store(
        selectedMainScenario,
        label,
        fo,
        names_list,
    )
