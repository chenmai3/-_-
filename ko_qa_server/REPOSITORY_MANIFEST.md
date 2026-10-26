# Repository Manifest

This directory is the only Python server source root for the refactored service.

The Git-root `README.md`, `requirements.txt`, and `requirements-dev.txt` are the
authoritative installation entry points and must also be committed.

## Commit

- `ko_qa_server.py`
- `config.yaml` (credential-free template only)
- `.gitignore`
- `.env.example`
- `vue_api/`
- `scripts/`
- `tests/`
- `CONFIGURATION.md`
- `REFACTOR_AUDIT.md`
- `REPOSITORY_MANIFEST.md`

The standard-document runtime assets below are source-controlled because the
document generation pipeline reads them at runtime:

- `vue_api/kdzn_hciqa/standard_document/generation_engine/prompt/`
- `vue_api/kdzn_hciqa/standard_document/generation_engine/latex_configure/`

## Do Not Commit

- `config.local.*`, `.env`, `.env.*`, or any credential-bearing configuration
- `user_vector_stores/`, `entity_vector/`, `rule_entity_vector_store_*/`, and `rulename_vector_store_*/`
- `bm25_index_dir/` and generated FAISS/keyword indexes
- `upload_file_user/`, `upload_files_json_all/`, and `graph_construct_files/`
- `temp_audio/`, `latex_cache/`, generated `result/`, logs, Python bytecode, and tool caches
- `vue_api/kdzn_hciqa/standard_document/generation_engine/cache/` terminology CSV and NPY caches
- A second `config.yaml` above this server directory

Vector indexes and user uploads are deployment data. Back them up and restore
them separately from the source repository.

## Pre-Commit Check

Run from `ko_qa_server`:

```powershell
D:\anaconda\envs\KO\python.exe -m pytest -q
D:\anaconda\envs\KO\python.exe -m ruff check vue_api tests scripts --select F401,F821,F822,F823
git status --short
```

Review the deletion set at the Git root before staging. The refactor deliberately
removes the old root scripts, legacy vector indexes, generated documents, and the
old `zhongshaoxuan/` tree after their supported behavior was moved under
`vue_api/`.
