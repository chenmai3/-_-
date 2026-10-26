import asyncio
import json
import re
import time
import uuid
from datetime import datetime
from functools import lru_cache
from pathlib import Path
from typing import Any, Dict, Optional

import pymysql
import yaml
from fastapi.responses import JSONResponse
from pypinyin import lazy_pinyin

from ..common.paths import (
    CONFIG_PATH,
    ENTITY_VECTOR_ROOT,
    JIAPU_ENTITY_VECTOR_STORE,
    LOCAL_ANALYSIS_FILE_ROOT,
    SERVER_ROOT,
    UPLOAD_JSON_ROOT,
    USER_VECTOR_STORES_ROOT,
    entity_vector_store_path,
)

__all__ = [
    "CONFIG_PATH",
    "ENTITY_VECTOR_ROOT",
    "JIAPU_ENTITY_VECTOR_STORE",
    "LOCAL_ANALYSIS_FILE_ROOT",
    "SERVER_ROOT",
    "UPLOAD_JSON_ROOT",
    "USER_VECTOR_STORES_ROOT",
    "entity_vector_store_path",
]

PACKAGE_ROOT = Path(__file__).resolve().parent

ANALYSIS_TASKS: Dict[str, Dict[str, Any]] = {}
ANALYSIS_TASK_LOCK = asyncio.Lock()


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
        print(f"[graph_construct] database connection error: {err}")
        return None


def han2pinyin_concat(text):
    return "".join(lazy_pinyin(text or ""))


def now_str() -> str:
    return datetime.now().strftime("%Y-%m-%d %H:%M:%S")


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


def frontend_json_string(payload: Dict[str, Any]):
    return frontend_success(json.dumps(payload, ensure_ascii=False))


def safe_path_name(name: str) -> str:
    name = str(name or "unknown").strip()
    name = Path(name).name
    name = re.sub(r'[\\/:*?"<>|]', "_", name)
    name = name.replace("..", "_")
    return name or "unknown"


def basename_any_path(value: Any) -> str:
    text = str(value).strip()
    if not text:
        return text
    text = text.rstrip("/\\")
    text = text.replace("\\", "/")
    return text.rsplit("/", 1)[-1]


async def create_analysis_task(*, user_id: str, original_filename: str, suffix: str) -> str:
    task_id = uuid.uuid4().hex
    ts = time.time()
    async with ANALYSIS_TASK_LOCK:
        ANALYSIS_TASKS[task_id] = {
            "taskId": task_id,
            "status": "pending",
            "userId": user_id,
            "originalFilename": original_filename,
            "suffix": suffix,
            "currentStep": "等待开始",
            "progress": 0,
            "total": 0,
            "finished": 0,
            "failed": 0,
            "message": "",
            "error": None,
            "result": None,
            "debug": {},
            "createdAt": now_str(),
            "updatedAt": now_str(),
            "createdTs": ts,
            "updatedTs": ts,
        }
    return task_id


async def update_analysis_task(task_id: str, **kwargs) -> None:
    async with ANALYSIS_TASK_LOCK:
        task = ANALYSIS_TASKS.get(task_id)
        if not task:
            return
        task.update(kwargs)
        task["updatedAt"] = now_str()
        task["updatedTs"] = time.time()


async def get_analysis_task(task_id: str) -> Optional[Dict[str, Any]]:
    async with ANALYSIS_TASK_LOCK:
        task = ANALYSIS_TASKS.get(task_id)
        if not task:
            return None
        return dict(task)


def public_task_data(task: Dict[str, Any], include_result: bool = False) -> Dict[str, Any]:
    data = {}
    for key, value in task.items():
        if key == "_asyncio_task":
            continue
        if key == "result" and not include_result:
            continue
        if key in ("createdTs", "updatedTs"):
            continue
        data[key] = value
    return data
