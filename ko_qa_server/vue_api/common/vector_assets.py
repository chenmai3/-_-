from __future__ import annotations

import os
import shutil
import uuid
from dataclasses import dataclass
from pathlib import Path


DEFAULT_EMBEDDING_DIMENSION = int(os.getenv("KO_QA_EMBEDDING_DIMENSION", "1024"))
FAISS_FILES = ("index.faiss", "index.pkl")


@dataclass(frozen=True)
class VectorStoreStatus:
    path: Path
    complete: bool
    dimension: int | None = None
    document_count: int | None = None
    error: str | None = None

    @property
    def compatible(self) -> bool:
        return self.complete and self.dimension == DEFAULT_EMBEDDING_DIMENSION


def inspect_vector_store(path) -> VectorStoreStatus:
    path = Path(path)
    missing = [name for name in FAISS_FILES if not (path / name).is_file()]
    if missing:
        return VectorStoreStatus(
            path=path,
            complete=False,
            error=f"missing files: {', '.join(missing)}",
        )

    try:
        import faiss

        index = faiss.read_index(str(path / "index.faiss"))
        return VectorStoreStatus(
            path=path,
            complete=True,
            dimension=int(index.d),
            document_count=int(index.ntotal),
        )
    except Exception as exc:
        return VectorStoreStatus(path=path, complete=False, error=str(exc))


def copy_compatible_vector_store(
    source,
    destination,
    expected_dimension: int = DEFAULT_EMBEDDING_DIMENSION,
) -> VectorStoreStatus:
    source = Path(source)
    destination = Path(destination)
    source_status = inspect_vector_store(source)
    if not source_status.complete:
        raise ValueError(f"invalid source vector store: {source_status.error}")
    if source_status.dimension != expected_dimension:
        raise ValueError(
            f"incompatible vector dimension: source={source_status.dimension}, "
            f"expected={expected_dimension}"
        )

    destination_status = inspect_vector_store(destination)
    if destination_status.complete:
        if destination_status.dimension != expected_dimension:
            raise ValueError(
                f"destination vector dimension is incompatible: "
                f"actual={destination_status.dimension}, expected={expected_dimension}"
            )
        return destination_status
    if destination.exists() and any(destination.iterdir()):
        raise FileExistsError(f"destination is non-empty but incomplete: {destination}")

    destination.parent.mkdir(parents=True, exist_ok=True)
    temp_path = destination.parent / f".{destination.name}.migrating-{uuid.uuid4().hex}"
    try:
        shutil.copytree(source, temp_path)
        copied_status = inspect_vector_store(temp_path)
        if not copied_status.complete or copied_status.dimension != expected_dimension:
            raise RuntimeError(f"copied vector store validation failed: {copied_status.error}")
        if destination.exists():
            destination.rmdir()
        temp_path.rename(destination)
    finally:
        if temp_path.exists():
            shutil.rmtree(temp_path)

    return inspect_vector_store(destination)


def copy_source_files_if_missing(source, destination) -> int:
    source = Path(source)
    destination = Path(destination)
    if not source.is_dir():
        return 0

    copied = 0
    for source_file in source.rglob("*"):
        if not source_file.is_file():
            continue
        relative_path = source_file.relative_to(source)
        destination_file = destination / relative_path
        if destination_file.exists():
            continue
        destination_file.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(source_file, destination_file)
        copied += 1
    return copied


def install_staged_vector_store(
    staged,
    destination,
    expected_dimension: int = DEFAULT_EMBEDDING_DIMENSION,
    replace: bool = False,
) -> VectorStoreStatus:
    staged = Path(staged)
    destination = Path(destination)
    staged_status = inspect_vector_store(staged)
    if not staged_status.complete or staged_status.dimension != expected_dimension:
        raise ValueError(
            f"staged vector store is invalid: dimension={staged_status.dimension}, "
            f"error={staged_status.error}"
        )
    if not (staged / "index").is_dir():
        raise ValueError(f"staged keyword index is missing: {staged / 'index'}")

    destination.parent.mkdir(parents=True, exist_ok=True)
    backup = destination.parent / f".{destination.name}.backup-{uuid.uuid4().hex}"
    if destination.exists() and not replace:
        raise FileExistsError(f"destination already exists: {destination}")

    try:
        if destination.exists():
            destination.rename(backup)
        staged.rename(destination)
    except Exception:
        if backup.exists() and not destination.exists():
            backup.rename(destination)
        raise
    else:
        if backup.exists():
            shutil.rmtree(backup)
    return inspect_vector_store(destination)
