import json
import queue
import time
from functools import lru_cache
from pathlib import Path
from typing import Any

import pymysql
import yaml
from fastapi.responses import JSONResponse, StreamingResponse
from pypinyin import lazy_pinyin

from ..common.paths import (
    CONFIG_PATH,
    ENTITY_VECTOR_ROOT,
    JIAPU_ENTITY_VECTOR_STORE,
    SERVER_ROOT,
    UPLOAD_JSON_ROOT,
    USER_VECTOR_STORES_ROOT,
    entity_vector_store_path,
)

__all__ = [
    "CONFIG_PATH",
    "ENTITY_VECTOR_ROOT",
    "JIAPU_ENTITY_VECTOR_STORE",
    "SERVER_ROOT",
    "UPLOAD_JSON_ROOT",
    "USER_VECTOR_STORES_ROOT",
    "entity_vector_store_path",
]

PACKAGE_ROOT = Path(__file__).resolve().parent
RULE_ENTITY_VECTOR_ROOT = ENTITY_VECTOR_ROOT


@lru_cache(maxsize=1)
def load_config():
    with CONFIG_PATH.open(encoding="utf-8") as f:
        return yaml.safe_load(f)


def connect_to_db():
    cfg = load_config()
    try:
        return pymysql.connect(
            host=cfg["KO_database"]["host"],
            user=cfg["KO_database"]["user"],
            password=cfg["KO_database"]["password"],
            database=cfg["KO_database"]["database"],
            charset=cfg["KO_database"]["charset"],
        )
    except pymysql.MySQLError as err:
        print(f"[rule_construct] database connection error: {err}")
        return None


def han2pinyin_concat(text):
    return "".join(lazy_pinyin(text or ""))


def now_ts():
    return time.perf_counter()


def cost_str(start):
    return f"{time.perf_counter() - start:.3f}s"


def frontend_success(data: Any = None, msg: str = "success", status_code: int = 200):
    return JSONResponse(
        status_code=status_code,
        content={"statusCode": status_code, "data": data, "msg": msg, "message": msg},
    )


def frontend_error(msg: str, status_code: int = 500, data: Any = None):
    return JSONResponse(
        status_code=status_code,
        content={"statusCode": status_code, "data": data, "msg": msg, "message": "error"},
    )


def frontend_json_string(payload: dict):
    return frontend_success(json.dumps(payload, ensure_ascii=False))


def sse_text(message: str) -> str:
    return f"data: {message}\n\n"


def sse_json(payload: dict) -> str:
    return f"data: {json.dumps(payload, ensure_ascii=False)}\n\n"


def stream_from_queue(event_queue: queue.Queue):
    def queue_consumer():
        while True:
            chunk = event_queue.get()
            if chunk is None:
                break
            yield chunk

    return StreamingResponse(
        queue_consumer(),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "Connection": "keep-alive"},
    )
