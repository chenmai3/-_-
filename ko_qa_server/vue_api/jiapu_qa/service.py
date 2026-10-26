import asyncio
import json
import uuid
from typing import Any

from fastapi import Request
from starlette.responses import StreamingResponse

from ..kdzn_hciqa.shared import Result, get_model, load_config
from .domain import FamilyAuxiliaryService, FamilySessionStateStore, NormalAnswerService
from .ko_graph import start_ko_graph_stream


family_auxiliary = FamilyAuxiliaryService()
family_session_states = FamilySessionStateStore()
normal_answer_service = NormalAnswerService()


def result(response=None, status=200, error_message=None):
    return dict(Result(response=response, status=status, errorMessage=error_message))


def parse_history(raw: Any) -> list[dict]:
    if raw is None:
        return []
    if isinstance(raw, dict):
        return [raw]
    if isinstance(raw, list):
        return [item for item in raw if isinstance(item, dict)]
    if isinstance(raw, str):
        value = raw.strip()
        if not value:
            return []
        try:
            parsed = json.loads(value)
            return parse_history(parsed)
        except json.JSONDecodeError:
            return [{"role": "user", "content": value}]
    return []


def extract_question(data: dict) -> str:
    for key in ("query", "wenti", "wenTi", "question", "text"):
        value = data.get(key)
        if value:
            return str(value)

    history = parse_history(data.get("u_input") or data.get("history") or data.get("messages"))
    for item in reversed(history):
        if item.get("role") == "user" and item.get("content"):
            return str(item["content"])
    if history and history[-1].get("content"):
        return str(history[-1]["content"])
    return ""


def build_graph_payload(data: dict) -> dict:
    qid = data.get("qid") or data.get("session_id") or uuid.uuid4().hex
    return {
        "qid": qid,
        "userId": data.get("userId") or data.get("userID") or data.get("userid") or "",
        "query": extract_question(data),
        "model_choose": data.get("model_choose") or data.get("model") or "Auto",
        "web": bool(data.get("web", False)),
        "bigbase": bool(data.get("bigbase", False)),
    }


async def run_ko_graph_stream(data: dict):
    payload = build_graph_payload(data)
    if not payload["query"]:
        return result(status=400, error_message="输入问题不能为空")
    history = parse_history(data.get("u_input") or data.get("history") or data.get("messages"))
    if not history:
        history = [{"role": "user", "content": payload["query"]}]
    return await start_ko_graph_stream(data, history, payload["query"])


async def collect_streaming_response(streaming_response):
    chunks = []
    async for chunk in streaming_response.body_iterator:
        if isinstance(chunk, bytes):
            chunks.append(chunk.decode("utf-8", errors="ignore"))
        else:
            chunks.append(str(chunk))
    return "".join(chunks)


def strip_sse_payload(text: str) -> str:
    lines = []
    for line in text.splitlines():
        if not line.startswith("data:"):
            continue
        payload = line[5:].strip()
        if payload in {"zxl", ""} or payload.startswith("<PrOSpLiT>"):
            continue
        try:
            metadata = json.loads(payload)
        except (ValueError, TypeError):
            metadata = None
        if isinstance(metadata, dict) and metadata.get("type") in {"status", "paths"}:
            continue
        lines.append(payload)
    return "\n".join(lines).replace("StReAmNeWlInE", "\n").replace("StReAmSpAcE", " ")


async def handle_ko_kg_mul_qa_stream(request: Request):
    data = await request.json()
    session_id = str(data.get("qid") or data.get("session_id") or uuid.uuid4().hex)
    family_session_states.start(session_id)
    response = await run_ko_graph_stream(data)
    if not hasattr(response, "body_iterator"):
        if isinstance(response, dict) and response.get("status", 200) >= 400:
            family_session_states.fail(session_id, response.get("errorMessage") or "处理失败")
        else:
            family_session_states.complete(session_id)
        return response

    async def tracked_body():
        try:
            async for chunk in response.body_iterator:
                yield chunk
        except asyncio.CancelledError:
            family_session_states.fail(session_id, "客户端已断开连接")
            raise
        except Exception as exc:
            family_session_states.fail(session_id, str(exc))
            raise
        else:
            family_session_states.complete(session_id)

    return StreamingResponse(
        tracked_body(),
        status_code=getattr(response, "status_code", 200),
        media_type=getattr(response, "media_type", "text/event-stream"),
        headers={"Cache-Control": "no-cache, no-transform", "X-Accel-Buffering": "no"},
    )


async def handle_ko_kg_mul_qa(request: Request):
    data = await request.json()
    session_id = str(data.get("qid") or data.get("session_id") or uuid.uuid4().hex)
    family_session_states.start(session_id)
    response = await run_ko_graph_stream(data)
    if not hasattr(response, "body_iterator"):
        if isinstance(response, dict) and response.get("status", 200) >= 400:
            family_session_states.fail(session_id, response.get("errorMessage") or "处理失败")
        else:
            family_session_states.complete(session_id)
        return response
    try:
        content = await collect_streaming_response(response)
    except Exception as exc:
        family_session_states.fail(session_id, str(exc))
        raise
    family_session_states.complete(session_id)
    return result(response={"message": strip_sse_payload(content), "events": content})


async def handle_judge_yitu(request: Request):
    data = await request.json()
    question = extract_question(data)
    if not question:
        return result(status=400, error_message="输入问题不能为空")
    intent = "jiapu Query" if any(word in question for word in ("家谱", "族谱", "祖", "父", "母", "子", "女", "兄", "弟", "姐", "妹", "妻", "夫", "曾国藩")) else "Chitchat"
    return result(response=intent)


async def handle_split_chenshu_wenti(request: Request):
    data = await request.json()
    text = str(data.get("u_input") or data.get("text") or "")
    if not text:
        return result(response={"chenShu": "", "wenTi": ""})
    response = await asyncio.to_thread(family_auxiliary.split_statement_question, text)
    return result(response=response)


async def handle_split_chenshu_wenti_json(request: Request):
    return await handle_split_chenshu_wenti(request)


async def handle_extract_tri(request: Request):
    data = await request.json()
    text = str(data.get("chenShu") or data.get("text") or "")
    response = await asyncio.to_thread(family_auxiliary.extract_triples, text)
    return result(response=response)


async def handle_extract_triplets(request: Request):
    data = await request.json()
    text = str(data.get("text") or data.get("chenShu") or "")
    extracted = await asyncio.to_thread(family_auxiliary.extract_triples, text)
    triples = extracted["triple"]
    know_tri = [triple for triple in triples if len(triple) == 3 and "？" not in triple]
    return result(response={"triples": triples, "know_tri": know_tri, "source": text})


async def handle_merge_ans(request: Request):
    data = await request.json()
    answer, items = await asyncio.to_thread(
        family_auxiliary.merge_answer,
        data.get("chenShuTiaomu"),
        data.get("hptTiaomu"),
        data.get("webTiaomu"),
        str(data.get("wenTi") or data.get("question") or ""),
    )
    return result(response={"answer": answer, "tm_list": items})


async def handle_merge_ans_mul(request: Request):
    data = await request.json()
    history = parse_history(data.get("history"))
    messages, items = await asyncio.to_thread(
        family_auxiliary.merge_multi_answer,
        data.get("chenShuTiaomu"),
        data.get("hptTiaomu"),
        data.get("webTiaomu"),
        history,
    )
    return result(response={"message": messages, "tm_list": items})


async def handle_normal_ans(request: Request):
    data = await request.json()
    history = parse_history(data.get("history"))
    if not history:
        return result(status=400, error_message="对话历史不能为空")
    return StreamingResponse(
        normal_answer_service.stream(history),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "Connection": "keep-alive"},
    )


async def handle_get_stage(request: Request):
    data = await request.json()
    state = family_session_states.get(data.get("session_id") or data.get("qid"))
    return result(response={"stage": state["stage"], "status": state["status"], "session_id": state["session_id"]})


async def handle_ko_kg_mul_qa_check(request: Request):
    data = await request.json()
    state = family_session_states.get(data.get("session_id") or data.get("qid"))
    return result(
        response={
            "message": state["message"],
            "stage": state["stage"],
            "status": state["status"],
            "session_id": state["session_id"],
        }
    )


def get_available_models():
    cfg = load_config()
    return {
        "default": get_model("Auto", "easy"),
        "qwen": cfg.get("qa_models", {}).get("qwen", {}),
    }
