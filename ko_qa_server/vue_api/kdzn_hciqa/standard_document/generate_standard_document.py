import queue
import json
import threading
import traceback
import time
import uuid
from types import SimpleNamespace

from fastapi import Request
from fastapi.responses import JSONResponse, StreamingResponse

from .request_intent import classify_standard_request
from ..qa_answer.rag_stream_answer import direct_qa_history, start_direct_question_worker


def sse_error(message: str) -> str:
    return f"event: error\ndata: {json.dumps({'section': 'error', 'content': message}, ensure_ascii=False)}\n\n"


def standard_queue_consumer(event_queue, timeout):
    """接口 gen_biaozhun 的内部函数：消费标准生成线程写入的 SSE 片段。"""
    last_event = time.monotonic()
    while True:
        try:
            chunk = event_queue.get(timeout=min(15, timeout))
        except queue.Empty:
            if time.monotonic() - last_event >= timeout:
                yield sse_error("标准生成请求超时，请稍后重试。")
                break
            yield ": keep-alive\n\n"
            continue
        if chunk is None:
            break
        last_event = time.monotonic()
        yield chunk


def run_standard_generation(input_data, state, event_queue):
    """Run the standard generation engine and always close the stream queue."""
    try:
        from .generation_engine.server import generate_content

        for event in generate_content(input_data, state):
            event_queue.put(event)
    except Exception as exc:
        traceback.print_exc()
        status = getattr(exc, "status_code", None)
        if status == 404:
            message = "标准生成模型或接口不存在，请检查 STANDARD_DOC_LLM_MODEL 和 STANDARD_DOC_LLM_BASE_URL。"
        elif status in (401, 403):
            message = "标准生成模型鉴权失败，请检查模型 API 密钥和访问权限。"
        elif isinstance(exc, FileNotFoundError) and 'STANDARD_BGE_MODEL_PATH' in str(exc):
            message = str(exc)
        else:
            message = "标准生成失败，请查看后端日志中的具体异常并重试。"
        event_queue.put(sse_error(message))
    finally:
        event_queue.put(None)


async def handle_gen_biaozhun(request: Request):
    """接口 gen_biaozhun：按输入内容流式生成标准文档内容和最终文档路径。"""
    try:
        query_data = await request.json()
    except Exception as exc:
        return JSONResponse({"status": "error", "message": f"请求体 JSON 解析失败: {exc}"}, status_code=400)

    if not isinstance(query_data, dict):
        return JSONResponse({"status": "error", "message": "请求体必须为 JSON 对象"}, status_code=400)
    input_data = query_data.get("query") or query_data.get("input")
    if not isinstance(input_data, str) or not input_data.strip():
        return JSONResponse({"status": "error", "message": "query 或 input 不能为空"}, status_code=400)
    input_data = input_data.strip()
    model_choose = query_data.get("model_choose") or "Auto"
    qid = str(query_data.get("qid") or uuid.uuid4().hex)

    event_queue = queue.Queue()
    state = SimpleNamespace(reasoning_content="", answer_content="", is_answering=False)
    threading.Thread(
        target=run_standard_request,
        args=(input_data, model_choose, qid, state, event_queue),
        daemon=True,
    ).start()
    return StreamingResponse(
        standard_queue_consumer(event_queue, timeout=1000),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache, no-transform", "X-Accel-Buffering": "no"},
    )


def run_standard_request(query, model_choose, qid, state, event_queue):
    """Classify before importing the document/embedding engine or starting it."""
    try:
        intent = classify_standard_request(query)
        event_queue.put(f"data: {json.dumps({'section': 'judge', 'content': intent})}\n\n")
        print(f"[标准生成意图] intent={intent}, model_choose={model_choose}")
        if intent == 'standard':
            # This worker owns closing the queue, including its error path.
            run_standard_generation(query, state, event_queue)
        elif intent == 'family':
            notice = '该问题属于家谱关系查询，请切换到“家谱问答”后提问。'
            event_queue.put(f"data: {json.dumps({'section': 'notice', 'content': notice}, ensure_ascii=False)}\n\n")
            event_queue.put(None)
        else:
            # Isolate ordinary chat here from conversations in other QA tabs.
            history_id = 'standard-chat:' + qid
            messages = list(direct_qa_history.get_user_qa_history(history_id))
            messages.append({'role': 'user', 'content': query})
            start_direct_question_worker(
                event_queue, state, model_choose, messages, history_id, query,
            )
    except Exception:
        traceback.print_exc()
        event_queue.put(sse_error('问题类型判断或模型连接失败，请稍后重试。'))
        event_queue.put(None)
