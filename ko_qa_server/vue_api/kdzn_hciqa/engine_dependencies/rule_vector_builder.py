import argparse
import re
from pathlib import Path

import pymysql
import yaml
from langchain_community.vectorstores import FAISS
from langchain_core.documents import Document

from ...common.neo4j_client import query_new_neo4j
from ..shared import CONFIG_PATH, rule_entity_vector_store_path
from .embedding_service import (
    EmbeddingServiceUnavailable,
    QwenEmbeddings,
    save_faiss_local_safe,
)


with CONFIG_PATH.open(encoding="utf-8") as config_file:
    cfg = yaml.safe_load(config_file)


def has_faiss_store(path) -> bool:
    path = (
        rule_entity_vector_store_path(path)
        if isinstance(path, int)
        else Path(path)
    )
    return (path / "index.faiss").is_file() and (path / "index.pkl").is_file()


def load_rule_vector_rows(table_name, rids=None):
    if not re.fullmatch(r"[A-Za-z0-9_]+", table_name):
        raise ValueError(f"非法规则表名: {table_name}")

    rid_values = sorted({int(rid) for rid in rids or []})
    connection = pymysql.connect(
        host=cfg["KO_database"]["host"],
        user=cfg["KO_database"]["user"],
        password=cfg["KO_database"]["password"],
        database=cfg["KO_database"]["database"],
        charset=cfg["KO_database"]["charset"],
    )
    try:
        query = (
            "SELECT rid, theme_name, theme_label, rulename, getin4simi "
            f"FROM {table_name}"
        )
        parameters = []
        if rid_values:
            placeholders = ", ".join(["%s"] * len(rid_values))
            query += f" WHERE rid IN ({placeholders})"
            parameters = rid_values
        query += " ORDER BY rid"
        with connection.cursor(pymysql.cursors.DictCursor) as cursor:
            cursor.execute(query, parameters)
            return list(cursor.fetchall())
    finally:
        connection.close()


def rule_record_payload(record):
    if isinstance(record, dict):
        return record
    if hasattr(record, "data"):
        return record.data()
    if isinstance(record, (tuple, list)) and record:
        return rule_record_payload(record[0])
    try:
        return dict(record)
    except (TypeError, ValueError):
        return {}


def _is_single_edit_apart(left, right):
    if left == right or abs(len(left) - len(right)) > 1:
        return False
    if len(left) == len(right):
        return sum(a != b for a, b in zip(left, right)) == 1

    shorter, longer = (
        (left, right) if len(left) < len(right) else (right, left)
    )
    short_index = 0
    differences = 0
    for char in longer:
        if short_index < len(shorter) and char == shorter[short_index]:
            short_index += 1
        else:
            differences += 1
            if differences > 1:
                return False
    return differences == 1


def normalize_rule_entry_query(rule_row):
    """Repair a one-character label typo when the canonical label is present."""
    query = str(rule_row.get("getin4simi") or "").strip()
    theme_label = str(rule_row.get("theme_label") or "").strip()
    if not query or not theme_label or theme_label not in query:
        return query

    label_pattern = re.compile(r"(?<=:)`?([A-Za-z][A-Za-z0-9_]*)`?")

    def replace_label(match):
        label = match.group(1)
        if label != theme_label and _is_single_edit_apart(label, theme_label):
            return match.group(0).replace(label, theme_label)
        return match.group(0)

    return label_pattern.sub(replace_label, query)


def collect_rule_entity_texts(rule_row):
    topic = str(rule_row.get("theme_name") or "")
    query = normalize_rule_entry_query(rule_row)
    if topic == "家谱问答" or not query:
        return []

    if topic == "家谱主题问答":
        graph_kind = "jiapu"
    elif topic == "轨交诊断":
        graph_kind = "kdzn"
    else:
        graph_kind = ""
    records = query_new_neo4j(query, kg=graph_kind)
    texts = []
    seen = set()
    for record in records:
        payload = rule_record_payload(record)
        text = "".join(
            str(payload.get(key) or "").strip()
            for key in ("R1Name", "R2Name", "RIName")
        )
        if text and text not in seen:
            texts.append(text)
            seen.add(text)
    return texts


def _documents_from_texts(texts):
    return [
        Document(
            page_content=text,
            metadata={"content": text, "id": str(index)},
        )
        for index, text in enumerate(texts)
    ]


def build_rule_entity_vector_store(rule_row, force=False):
    rid = int(rule_row["rid"])
    path = rule_entity_vector_store_path(rid)
    if has_faiss_store(path) and not force:
        return {"rid": rid, "status": "exists", "path": str(path)}

    texts = collect_rule_entity_texts(rule_row)
    if not texts:
        return {
            "rid": rid,
            "status": "empty",
            "path": str(path),
            "documents": 0,
        }

    embeddings = QwenEmbeddings()
    documents = _documents_from_texts(texts)
    vector_store = FAISS.from_documents(
        documents=documents,
        embedding=embeddings,
    )
    save_faiss_local_safe(vector_store, path)
    return {
        "rid": rid,
        "status": "built",
        "path": str(path),
        "documents": len(documents),
        "dimension": int(vector_store.index.d),
    }


def vector_generate(table_name="ko_kdzn_rule_construct", rids=None, force=False):
    rows = load_rule_vector_rows(table_name, rids=rids)
    requested = sorted({int(rid) for rid in rids or []})
    found = {int(row["rid"]) for row in rows}
    missing = sorted(set(requested) - found)
    if missing:
        print(f"[WARN] 数据库中未找到 RID: {missing}")

    results = []
    for row in rows:
        result = build_rule_entity_vector_store(row, force=force)
        results.append(result)
        print(
            f"[RuleVector] rid={result['rid']}, status={result['status']}, "
            f"documents={result.get('documents', '-')}, path={result['path']}"
        )
    return results


def main(argv=None):
    parser = argparse.ArgumentParser(
        description="Generate rule entity vector stores."
    )
    parser.add_argument(
        "--table",
        default="ko_kdzn_rule_construct",
        help="Rule table name.",
    )
    scope = parser.add_mutually_exclusive_group(required=True)
    scope.add_argument(
        "--rid",
        action="append",
        type=int,
        help="RID to build; repeat as needed.",
    )
    scope.add_argument(
        "--all",
        action="store_true",
        help="Build every rule in the table.",
    )
    parser.add_argument(
        "--force",
        action="store_true",
        help="Rebuild stores that already exist.",
    )
    args = parser.parse_args(argv)
    try:
        return vector_generate(
            args.table,
            rids=None if args.all else args.rid,
            force=args.force,
        )
    except EmbeddingServiceUnavailable as exc:
        raise SystemExit(str(exc)) from exc


if __name__ == "__main__":
    main()
