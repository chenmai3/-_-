import json
import os
import shutil
import uuid
from dataclasses import dataclass, field
from pathlib import Path

from langchain_community.vectorstores import FAISS

from ...common.keyword_index import rebuild_keyword_index
from ...common.paths import UPLOAD_FILE_ROOT, UPLOAD_JSON_ROOT, USER_VECTOR_STORES_ROOT
from ...common.vector_assets import (
    DEFAULT_EMBEDDING_DIMENSION,
    inspect_vector_store,
    install_staged_vector_store,
)
from .embedding_service import QwenEmbeddings, save_faiss_local_safe
from .file_text_extractor import SUPPORTED_REMOTE_TYPES, extract_text_from_file, extract_text_from_TXT
from .vector_store_builder import load_documents


TEXT_FILE_TYPES = {
    "CSS", "HTML", "INI", "JS", "JSON", "LOG", "MD", "PY", "SQL",
    "TS", "TSV", "TXT", "XML", "YAML", "YML",
}


class UnsupportedUserFile(ValueError):
    pass


@dataclass
class UserStoreRebuildResult:
    user_id: str
    status: str
    documents: int = 0
    files_indexed: list[str] = field(default_factory=list)
    files_failed: dict[str, str] = field(default_factory=dict)
    files_skipped: dict[str, str] = field(default_factory=dict)
    path: str = ""


def _validate_user_id(user_id: str) -> str:
    user_id = str(user_id or "").strip()
    if not user_id or Path(user_id).name != user_id or user_id in {".", ".."}:
        raise ValueError(f"invalid user id: {user_id!r}")
    return user_id


def extract_documents_from_user_file(file_path: Path, reuse_extracted: bool = False):
    file_type = file_path.suffix.lstrip(".").upper()
    if file_type not in TEXT_FILE_TYPES and file_type not in SUPPORTED_REMOTE_TYPES:
        raise UnsupportedUserFile(f"unsupported file type: {file_type or '<none>'}")
    max_text_bytes = int(os.getenv("KO_QA_MAX_TEXT_SOURCE_BYTES", str(2 * 1024 * 1024)))
    if file_type in TEXT_FILE_TYPES and file_path.stat().st_size > max_text_bytes:
        raise UnsupportedUserFile(
            f"text source exceeds limit: bytes={file_path.stat().st_size}, limit={max_text_bytes}"
        )

    cached_json = UPLOAD_JSON_ROOT / f"{file_path.name}.json"
    if reuse_extracted and cached_json.is_file():
        return load_documents(str(cached_json))

    if file_type in TEXT_FILE_TYPES:
        _, json_path = extract_text_from_TXT(str(file_path), file_path.name)
    else:
        _, json_path = extract_text_from_file(str(file_path), file_path.name, file_type)
    if not json_path:
        raise RuntimeError(f"text extraction failed for {file_path.name}")
    documents = load_documents(json_path)
    if not documents:
        raise RuntimeError(f"no indexable text extracted from {file_path.name}")
    return documents


def rebuild_user_vector_store(
    user_id: str,
    source_root=UPLOAD_FILE_ROOT,
    destination_root=USER_VECTOR_STORES_ROOT,
    replace: bool = False,
    allow_partial: bool = False,
    reuse_extracted: bool = False,
    embedding=None,
) -> UserStoreRebuildResult:
    user_id = _validate_user_id(user_id)
    source_dir = Path(source_root) / user_id
    destination = Path(destination_root) / user_id
    if not source_dir.is_dir():
        raise FileNotFoundError(f"upload source directory does not exist: {source_dir}")

    files = sorted(path for path in source_dir.rglob("*") if path.is_file())
    if not files:
        raise ValueError(f"no upload source files found for user {user_id}")

    documents = []
    ranges = {}
    indexed = []
    failed = {}
    skipped = {}
    for file_path in files:
        try:
            file_documents = extract_documents_from_user_file(file_path, reuse_extracted=reuse_extracted)
            start = len(documents)
            documents.extend(file_documents)
            ranges[str(file_path.relative_to(source_dir))] = [start, len(documents) - 1]
            indexed.append(str(file_path.relative_to(source_dir)))
        except UnsupportedUserFile as exc:
            skipped[str(file_path.relative_to(source_dir))] = str(exc)
        except Exception as exc:
            failed[str(file_path.relative_to(source_dir))] = str(exc)

    if failed and not allow_partial:
        return UserStoreRebuildResult(
            user_id=user_id,
            status="failed",
            files_indexed=indexed,
            files_failed=failed,
            files_skipped=skipped,
            path=str(destination),
        )
    if not documents:
        return UserStoreRebuildResult(
            user_id=user_id,
            status="empty",
            files_failed=failed,
            files_skipped=skipped,
            path=str(destination),
        )

    destination_root = Path(destination_root)
    destination_root.mkdir(parents=True, exist_ok=True)
    staged = destination_root / f".{user_id}.rebuilding-{uuid.uuid4().hex}"
    try:
        print(
            f"[UserStore] user={user_id}, files={len(indexed)}, "
            f"documents={len(documents)}, failed_files={len(failed)}"
        )
        ids = [str(index) for index in range(len(documents))]
        vector_store = FAISS.from_documents(
            documents=documents,
            embedding=embedding or QwenEmbeddings(),
            ids=ids,
        )
        save_faiss_local_safe(vector_store, staged)
        with (staged / "doc_rangs.json").open("w", encoding="utf-8") as file:
            json.dump(ranges, file, ensure_ascii=False, indent=2)
        keyword_documents = rebuild_keyword_index(staged)

        status = inspect_vector_store(staged)
        if (
            not status.complete
            or status.dimension != DEFAULT_EMBEDDING_DIMENSION
            or status.document_count != len(documents)
            or keyword_documents != len(documents)
        ):
            raise RuntimeError(
                f"rebuilt store validation failed: dimension={status.dimension}, "
                f"faiss_documents={status.document_count}, keyword_documents={keyword_documents}"
            )
        installed = install_staged_vector_store(staged, destination, replace=replace)
        return UserStoreRebuildResult(
            user_id=user_id,
            status="rebuilt",
            documents=installed.document_count or 0,
            files_indexed=indexed,
            files_failed=failed,
            files_skipped=skipped,
            path=str(destination),
        )
    finally:
        if staged.exists():
            shutil.rmtree(staged)
