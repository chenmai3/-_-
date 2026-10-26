import argparse
import sys
from pathlib import Path


SERVER_ROOT = Path(__file__).resolve().parents[1]
if str(SERVER_ROOT) not in sys.path:
    sys.path.insert(0, str(SERVER_ROOT))

from vue_api.common.paths import UPLOAD_FILE_ROOT, USER_VECTOR_STORES_ROOT
from vue_api.common.keyword_index import rebuild_keyword_index
from vue_api.common.vector_assets import (
    DEFAULT_EMBEDDING_DIMENSION,
    copy_compatible_vector_store,
    copy_source_files_if_missing,
    inspect_vector_store,
)
from vue_api.kdzn_hciqa.engine_dependencies.user_store_rebuilder import rebuild_user_vector_store


def audit(root: Path) -> int:
    if not root.is_dir():
        print(f"[WARN] vector root does not exist: {root}")
        return 1

    failures = 0
    for path in sorted(item for item in root.iterdir() if item.is_dir()):
        status = inspect_vector_store(path)
        state = "OK" if status.compatible else "REBUILD"
        print(
            f"[{state}] {path.name}: dimension={status.dimension}, "
            f"documents={status.document_count}, error={status.error or '-'}"
        )
        failures += int(not status.compatible)
    return int(failures > 0)


def migrate_users(source_server: Path, user_ids: list[str], copy_uploads: bool) -> int:
    source_vectors = source_server / "user_vector_stores"
    source_uploads = source_server / "upload_file_user"
    if not source_vectors.is_dir():
        raise FileNotFoundError(f"source vector root does not exist: {source_vectors}")

    candidates = user_ids or sorted(item.name for item in source_vectors.iterdir() if item.is_dir())
    migrated = skipped = failed = 0
    for user_id in candidates:
        source = source_vectors / user_id
        status = inspect_vector_store(source)
        upload_count = 0
        if copy_uploads:
            upload_count = copy_source_files_if_missing(
                source_uploads / user_id,
                UPLOAD_FILE_ROOT / user_id,
            )
        if not status.complete or status.dimension != DEFAULT_EMBEDDING_DIMENSION:
            print(
                f"[SKIP] {user_id}: dimension={status.dimension}, "
                f"documents={status.document_count}, upload_files_copied={upload_count}, "
                f"reason={status.error or 'dimension mismatch'}"
            )
            skipped += 1
            continue
        try:
            destination = USER_VECTOR_STORES_ROOT / user_id
            copied = copy_compatible_vector_store(source, destination)
            keyword_documents = rebuild_keyword_index(destination)
            print(
                f"[OK] {user_id}: dimension={copied.dimension}, "
                f"documents={copied.document_count}, keyword_documents={keyword_documents}, "
                f"upload_files_copied={upload_count}"
            )
            migrated += 1
        except Exception as exc:
            print(f"[ERROR] {user_id}: {exc}")
            failed += 1

    print(f"[SUMMARY] migrated={migrated}, skipped={skipped}, failed={failed}")
    return int(failed > 0)


def parse_args():
    parser = argparse.ArgumentParser(description="Audit and migrate KO-QA vector assets.")
    subparsers = parser.add_subparsers(dest="command", required=True)

    audit_parser = subparsers.add_parser("audit", help="Inspect FAISS stores under a root directory.")
    audit_parser.add_argument("--root", type=Path, default=USER_VECTOR_STORES_ROOT)

    migrate_parser = subparsers.add_parser(
        "migrate-users",
        help="Copy user stores whose FAISS dimension matches the current embedding model.",
    )
    migrate_parser.add_argument("--source-server", type=Path, required=True)
    migrate_parser.add_argument("--user-id", action="append", default=[])
    migrate_parser.add_argument("--copy-uploads", action="store_true")

    rebuild_parser = subparsers.add_parser(
        "rebuild-users",
        help="Rebuild user stores from upload source files with the current embedding model.",
    )
    rebuild_parser.add_argument("--user-id", action="append", required=True)
    rebuild_parser.add_argument("--source-root", type=Path, default=UPLOAD_FILE_ROOT)
    rebuild_parser.add_argument("--replace", action="store_true")
    rebuild_parser.add_argument("--allow-partial", action="store_true")
    rebuild_parser.add_argument("--reuse-extracted", action="store_true")
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    if args.command == "audit":
        return audit(args.root)
    if args.command == "migrate-users":
        return migrate_users(args.source_server, args.user_id, args.copy_uploads)

    failures = 0
    for user_id in args.user_id:
        try:
            result = rebuild_user_vector_store(
                user_id,
                source_root=args.source_root,
                replace=args.replace,
                allow_partial=args.allow_partial,
                reuse_extracted=args.reuse_extracted,
            )
            print(
                f"[{result.status.upper()}] {result.user_id}: documents={result.documents}, "
                f"files_indexed={len(result.files_indexed)}, files_failed={result.files_failed or '-'}, "
                f"files_skipped={result.files_skipped or '-'}, "
                f"path={result.path}"
            )
            failures += int(result.status != "rebuilt")
        except Exception as exc:
            print(f"[ERROR] {user_id}: {type(exc).__name__}: {exc}")
            failures += 1
    return int(failures > 0)


if __name__ == "__main__":
    raise SystemExit(main())
