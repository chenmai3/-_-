import ast
import json
import os
import queue
import time
from datetime import datetime, timedelta
from functools import lru_cache
from pathlib import Path
from typing import Any, Optional

import pymysql
import yaml
from fastapi.responses import JSONResponse
from pydantic import BaseModel
from starlette.responses import StreamingResponse

from ..common.paths import (
    CONFIG_PATH,
    EMBEDDING_MODEL_ROOT,
    ENTITY_VECTOR_ROOT,
    JIAPU_ENTITY_VECTOR_STORE,
    LOCAL_ANALYSIS_FILE_ROOT,
    RULE_ENTITY_VECTOR_KDZN_ROOT,
    SERVER_ROOT,
    TEMP_AUDIO_ROOT,
    UPLOAD_FILE_ROOT,
    UPLOAD_JSON_ROOT,
    USER_VECTOR_STORES_ROOT,
    entity_vector_store_path,
    rule_entity_vector_store_path,
)

__all__ = [
    "CONFIG_PATH",
    "EMBEDDING_MODEL_ROOT",
    "ENTITY_VECTOR_ROOT",
    "JIAPU_ENTITY_VECTOR_STORE",
    "LOCAL_ANALYSIS_FILE_ROOT",
    "RULE_ENTITY_VECTOR_KDZN_ROOT",
    "SERVER_ROOT",
    "TEMP_AUDIO_ROOT",
    "UPLOAD_FILE_ROOT",
    "UPLOAD_JSON_ROOT",
    "USER_VECTOR_STORES_ROOT",
    "entity_vector_store_path",
    "rule_entity_vector_store_path",
]

PACKAGE_ROOT = Path(__file__).resolve().parent
FFMPEG_EXECUTABLE = os.getenv("FFMPEG_PATH") or "ffmpeg"


@lru_cache(maxsize=1)
def load_config():
    # 公共函数：kdzn_hciqa.vue 下多个问答/上传接口都会读 config.yaml。
    with open(CONFIG_PATH, encoding="utf-8") as f:
        return yaml.safe_load(f)


class Result(BaseModel):
    response: Any = None
    stream: bool = False
    time: float = None
    status: int = 200
    errorMessage: Optional[str] = None
    docs: Any = None

    def __init__(self, **kwargs):
        if "time" not in kwargs:
            kwargs["time"] = time.time()
        super().__init__(**kwargs)


class UserQAHistory:
    # 公共内存历史：ko4csg_hci、receive_question 都会维护 qid 维度的问答历史。
    def __init__(self):
        self.user_data = {}

    def add_or_update_user_qa(self, qa_box_id, qa_pair):
        if qa_box_id not in self.user_data:
            self.user_data[qa_box_id] = {"qa_list": [], "last_updated": datetime.now()}
        self.user_data[qa_box_id]["qa_list"].extend(qa_pair)
        self.user_data[qa_box_id]["last_updated"] = datetime.now()

    def remove_old_users(self):
        one_day_ago = datetime.now() - timedelta(days=1)
        users_to_remove = [
            qa_box_id
            for qa_box_id, data in self.user_data.items()
            if data["last_updated"] < one_day_ago
        ]
        for qa_box_id in users_to_remove:
            del self.user_data[qa_box_id]

    def get_user_qa_history(self, qa_box_id):
        return self.user_data.get(qa_box_id, {}).get("qa_list", [])


kdzn_history = UserQAHistory()
QA_history = UserQAHistory()
_kochatbot = None


def get_kochatbot():
    """公共函数：upload 和 receive_question 共同使用的知识库问答对象。"""
    global _kochatbot
    if _kochatbot is None:
        from .engine_dependencies.knowledge_base_chatbot import Chatzxl

        _kochatbot = Chatzxl()
        _kochatbot.init_database()
    return _kochatbot


def queue_consumer(q, timeout):
    # 公共 SSE 消费器：从队列持续输出给前端，超时后返回 SSE 错误提示。
    while True:
        try:
            chunk = q.get(timeout=timeout)
        except queue.Empty:
            yield "data: 【请求超时，请稍后重试。】\n\n"
            break
        if chunk is None:
            break
        yield chunk


def stream_response(event_queue, timeout=80):
    # 公共流式响应封装：所有 post_stream 类型接口都可以复用。
    return StreamingResponse(queue_consumer(event_queue, timeout=timeout), media_type="text/event-stream")


def sse_message(message: str) -> str:
    return f"data: <PrOSpLiT>{message}</PrOSpLiT>\n\n"


def sse_error(message: str) -> str:
    payload = json.dumps({"error": message}, ensure_ascii=False)
    return f"data: {payload}\n\n"


def connect_to_db():
    # 公共数据库连接：会话历史、主题权限、规则生成后入库都会用到。
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
        print(f"[kdzn_hciqa.common] database connection error: {err}")
        return None


def parse_history_qa(raw):
    # 公共历史解析：兼容 JSON、Python 字面量、bytes 和空值。
    if raw is None:
        return None
    if isinstance(raw, (dict, list)):
        return raw
    if isinstance(raw, (bytes, bytearray)):
        raw = raw.decode("utf-8", errors="ignore")
    value = str(raw).strip()
    if not value:
        return None
    try:
        return json.loads(value)
    except json.JSONDecodeError:
        try:
            return ast.literal_eval(value)
        except Exception:
            return value


def load_history_qa(qid: str):
    # ko4csg_hci 内部函数：读取当前 qid 已持久化的历史问答。
    db_connection = connect_to_db()
    if not db_connection:
        return None, JSONResponse({"status": "error", "message": "数据库连接失败"}, status_code=500)

    try:
        history_qa = []
        with db_connection.cursor(pymysql.cursors.DictCursor) as cursor:
            cursor.execute(
                """
                SELECT history_qa
                FROM ko_kdzn_history_conversations
                WHERE id = %s
                """,
                (qid,),
            )
            rows = cursor.fetchall()

        for row in rows:
            parsed = parse_history_qa(row.get("history_qa"))
            if isinstance(parsed, list):
                history_qa.extend(parsed)
            elif parsed is not None:
                history_qa.append(parsed)
        return history_qa, None
    except pymysql.MySQLError as err:
        print(f"[kdzn_hciqa.common] load_history_qa error: {err}")
        return [], None
    finally:
        db_connection.close()


def update_sql_history(qid, history_qa):
    # 公共历史写回：ko4csg_hci、receive_question 在回答结束后都会调用。
    db_connection = connect_to_db()
    if not db_connection:
        return False

    try:
        if not isinstance(history_qa, str):
            history_qa = json.dumps(history_qa, ensure_ascii=False, default=str)

        with db_connection.cursor() as cursor:
            cursor.execute(
                "UPDATE ko_kdzn_history_conversations SET history_qa=%s WHERE id=%s LIMIT 1",
                (history_qa, qid),
            )
            affected = cursor.rowcount

        db_connection.commit()
        return affected > 0
    except pymysql.MySQLError as err:
        db_connection.rollback()
        print(f"[kdzn_hciqa.common] update_sql_history error: {err}")
        return False
    finally:
        db_connection.close()


def get_model(model_name, difficulty=None):
    # 公共模型选择：ko4csg_hci 和 RAG 问答都会按前端选择映射具体模型名。
    cfg = load_config()
    model_mapping = {
        "Auto": {
            "easy": cfg["qa_models"]["qwen"]["DeepSeekV3"],
            "think": cfg["qa_models"]["qwen"]["DeepSeekR1"],
        },
        "Qwen": cfg["small_models"]["qwen"]["qwen2_model_name"],
        "DeepSeekV3": cfg["qa_models"]["qwen"]["DeepSeekV3"],
        "DeepSeekR1": cfg["qa_models"]["qwen"]["DeepSeekR1"],
        "Kimi": cfg["qa_models"]["kimi"]["model_name"],
        "QwQ": cfg["qa_models"]["qwen"]["QwQ"],
        "Spark": cfg["qa_models"]["spark"]["model_name"],
        "ZhipuAI": cfg["qa_models"]["zhipuai"]["model_name"],
    }
    model_value = model_mapping.get(model_name, model_mapping["DeepSeekR1"])
    if isinstance(model_value, dict):
        result = model_value.get(difficulty, model_mapping["DeepSeekR1"])
    else:
        result = model_value
    print(f"[get_model] model_choose={model_name}, difficulty={difficulty}, actual_model={result}")
    return result


def is_thinking_selection(model_choose, difficulty=None):
    # 与 get_model 的映射保持一致：该选择是否最终落到 DeepSeek 思考模型（DeepSeekR1）。
    if model_choose == "DeepSeekR1":
        return True
    if model_choose == "DeepSeekV3":
        return False
    if model_choose == "Auto":
        return difficulty != "easy"
    return False


def is_reasoning_model(model_name, is_thinking=False):
    # 是否走思考流式分支（返回 reasoning_content）：QwQ 始终思考；DeepSeek 由 is_thinking 决定。
    cfg = load_config()
    deepseek_models = {
        cfg["qa_models"]["qwen"]["DeepSeekV3"],
        cfg["qa_models"]["qwen"]["DeepSeekR1"],
    }
    if model_name == cfg["qa_models"]["qwen"]["QwQ"]:
        return True
    return is_thinking and model_name in deepseek_models


def thinking_extra_body(model_name, is_thinking=False):
    # DeepSeek 混合思考模型用 enable_thinking 开关；QwQ（qwen3.7-plus）也是混合思考
    # 模型，选择 QwQ 即表示要思考，固定开启才会返回 reasoning_content。
    cfg = load_config()
    deepseek_models = {
        cfg["qa_models"]["qwen"]["DeepSeekV3"],
        cfg["qa_models"]["qwen"]["DeepSeekR1"],
    }
    if model_name in deepseek_models:
        return {"enable_thinking": is_thinking}
    if model_name == cfg["qa_models"]["qwen"]["QwQ"]:
        return {"enable_thinking": True}
    return {}


USER_ERROR_MESSAGE = "抱歉，模型暂时无法回答，请稍后重试。"
SENSITIVE_ERROR_MESSAGE = "抱歉，这个问题我不能回答"
EMPTY_MODEL_RESPONSE_MESSAGE = "模型未返回可显示的回答，请稍后重试。"


def is_model_not_found(exc):
    # 判断异常是否为“模型不存在”类错误（404 model_not_found），用于触发模型回退。
    return (
        getattr(exc, "status_code", None) == 404
        or getattr(exc, "code", None) == "model_not_found"
    )


def create_answer_stream_with_fallback(create_stream, model_name):
    """Retry unavailable models with the configured Qwen answer model."""
    try:
        return create_stream(model_name), model_name
    except Exception as exc:
        if not is_model_not_found(exc):
            raise

        fallback_model = get_model("Qwen")
        if fallback_model == model_name:
            raise
        return create_stream(fallback_model), fallback_model
