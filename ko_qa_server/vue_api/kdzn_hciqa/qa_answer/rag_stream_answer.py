import queue
import threading
import time
import traceback
from types import SimpleNamespace

from fastapi import Request
from fastapi.responses import JSONResponse, StreamingResponse
from openai import OpenAI

from .prompt_security import is_internal_prompt_request, prepare_qa_messages
from ..engine_dependencies.llm_clients import llm_config
from ..shared import (
    QA_history,
    UserQAHistory,
    EMPTY_MODEL_RESPONSE_MESSAGE,
    SENSITIVE_ERROR_MESSAGE,
    USER_ERROR_MESSAGE,
    get_kochatbot,
    get_model,
    is_model_not_found,
    is_reasoning_model,
    is_thinking_selection,
    thinking_extra_body,
    kdzn_history,
    load_config,
    queue_consumer,
    update_sql_history,
)


STREAM_NEWLINE = "StReAmNeWlInE"
STREAM_SPACE = "StReAmSpAcE"

_llm = None
cfg = load_config()
direct_qa_history = UserQAHistory()


def get_llm():
    """receive_question 内部函数：延迟初始化旧逻辑使用的大模型配置对象。"""
    global _llm
    if _llm is None:
        _llm = llm_config()
    return _llm


def encode_stream_text(text: str, keep_reasoning_quote=False) -> str:
    """Encode text with placeholders expected by the existing frontend stream parser."""
    newline = f"{STREAM_NEWLINE} > " if keep_reasoning_quote else STREAM_NEWLINE
    return text.replace("\n", newline).replace(" ", STREAM_SPACE)


def sse_data(content: str) -> str:
    return f"data: {content}\n\n"


def build_chat_params(provider_config, *, model_name, messages, stream=True, is_thinking=False):
    """Keep OpenAI-compatible model parameters explicit at every call site."""
    params = {
        "model": model_name,
        "messages": prepare_qa_messages(messages),
        "temperature": provider_config.get("temperature", 0.1),
        "top_p": provider_config.get("top_p", 0.8),
        "max_tokens": provider_config.get("max_tokens", 4096),
        "stream": stream,
    }
    extra_body = thinking_extra_body(model_name, is_thinking)
    if extra_body:
        params["extra_body"] = extra_body
    return params


def create_chat_stream(model_name, messages, is_thinking=False):
    """Create the streaming response object for the selected model provider."""
    print(f"[LLM调用] model={model_name}, is_thinking={is_thinking}, extra_body={thinking_extra_body(model_name, is_thinking)}")
    if model_name == cfg["qa_models"]["zhipuai"]["model_name"]:
        provider_config = cfg["qa_models"]["zhipuai"]
        client = OpenAI(
            api_key=provider_config["api_keys"],
            base_url=provider_config["base_url"],
        )
        return client.chat.completions.create(**build_chat_params(provider_config, model_name=model_name, messages=messages))

    if model_name == cfg["qa_models"]["kimi"]["model_name"]:
        provider_config = cfg["qa_models"]["kimi"]
        client = OpenAI(
            api_key=provider_config["api_key"],
            base_url=provider_config["base_url"],
        )
        return client.chat.completions.create(**build_chat_params(provider_config, model_name=model_name, messages=messages))

    provider_config = cfg["qa_models"]["qwen"]
    client = OpenAI(
        api_key=provider_config["api_key"],
        base_url=provider_config["base_url"],
    )
    return client.chat.completions.create(**build_chat_params(provider_config, model_name=model_name, messages=messages, is_thinking=is_thinking))


def stream_spark_answer(messages):
    """Yield Spark SSE chunks and the answer delta used for history persistence."""
    print(f"[LLM调用] provider=Spark, model={cfg['qa_models']['spark']['model_name']}")
    query = messages[-1]["content"]
    for delta in get_llm().spark(
        appid=cfg["qa_models"]["spark"]["appid"],
        api_key=cfg["qa_models"]["spark"]["api_keys"],
        api_secret=cfg["qa_models"]["spark"]["api_secret"],
        gpt_url=cfg["qa_models"]["spark"]["gpt_url"],
        domain=cfg["qa_models"]["spark"]["domain"],
        query=query,
    ):
        yield sse_data(encode_stream_text(delta)), delta


def stream_reasoning_answer(response, model_name):
    """Yield SSE chunks for reasoning-capable models.

    头部“思考内容”改为在首个有效分片成功返回后才输出，避免模型 404 回退时
    残留一个空的思考块、把后续普通模型的回答也套进去。
    """
    is_answering = False
    header_yielded = False

    for chunk in response:
        if not getattr(chunk, "choices", None):
            continue

        choice = chunk.choices[0]
        if getattr(choice, "finish_reason", None) == "sensitive":
            yield sse_data(SENSITIVE_ERROR_MESSAGE), SENSITIVE_ERROR_MESSAGE
            break
        delta = choice.delta
        reasoning = getattr(delta, "reasoning_content", None)
        content = getattr(delta, "content", None)

        if reasoning or content:
            print(
                f"[stream_reasoning_answer] reasoning={bool(reasoning)}"
                f"(len={len(reasoning) if reasoning else 0})"
                f" content={bool(content)}(len={len(content) if content else 0})"
            )

        if not header_yielded and (reasoning or content):
            header_yielded = True
            yield sse_data(f"> **思考内容：**{STREAM_NEWLINE}{STREAM_NEWLINE} > "), ""

        if reasoning:
            if model_name == "qwq-32b":
                yield sse_data(reasoning), ""
            else:
                yield sse_data(encode_stream_text(reasoning, keep_reasoning_quote=True)), ""
        # The transition chunk can carry both the last reasoning and first answer.
        if content:
            if not is_answering:
                is_answering = True
                if model_name == "qwq-32b":
                    yield sse_data("**开始回答：**"), ""
                else:
                    yield sse_data(f"{STREAM_NEWLINE} --- {STREAM_NEWLINE}"), ""
                    yield sse_data(f"**开始回答：** {STREAM_NEWLINE}{STREAM_NEWLINE} "), ""

            text_delta = encode_stream_text(content)
            yield sse_data(text_delta), content

        time.sleep(0.01)


def stream_regular_answer(response):
    """Yield SSE chunks for non-reasoning models."""
    chunk_count = 0
    for msg in response:
        if not getattr(msg, "choices", None):
            continue
        choice = msg.choices[0]
        if getattr(choice, "finish_reason", None) == "sensitive":
            yield sse_data(SENSITIVE_ERROR_MESSAGE), SENSITIVE_ERROR_MESSAGE
            break
        delta = choice.delta
        reasoning = getattr(delta, "reasoning_content", None)
        content = getattr(delta, "content", None)
        if reasoning or content:
            chunk_count += 1
            print(
                f"[stream_regular_answer] reasoning={bool(reasoning)}"
                f"(len={len(reasoning) if reasoning else 0})"
                f" content={bool(content)}(len={len(content) if content else 0})"
            )
        if content:
            text_delta = encode_stream_text(content)
            yield sse_data(text_delta), text_delta
            time.sleep(0.01)
    print(f"[stream_regular_answer] done, chunks={chunk_count}")


def _make_chunk_stream(model_name, messages, is_thinking):
    """根据模型创建对应的 SSE 分片流（推理模型走思考分支，其余走普通分支）。"""
    response = create_chat_stream(model_name, messages, is_thinking)
    if is_reasoning_model(model_name, is_thinking):
        return stream_reasoning_answer(response, model_name)
    return stream_regular_answer(response)


def _stream_with_fallback(model_name, messages, is_thinking):
    """生成 (event, answer_delta) 分片流，遇到模型不存在时自动回退到 Qwen。"""
    fallback_model = get_model("Qwen")
    active_model = model_name
    chunk_stream = None

    while True:
        if chunk_stream is None:
            try:
                chunk_stream = _make_chunk_stream(active_model, messages, is_thinking)
            except Exception as exc:
                if is_model_not_found(exc) and active_model != fallback_model:
                    print(f"[rag_stream_answer] model {active_model} not found, fallback to {fallback_model}: {exc}")
                    active_model = fallback_model
                    continue
                raise

        try:
            event, answer_delta = next(chunk_stream)
        except StopIteration:
            return
        except Exception as exc:
            if is_model_not_found(exc) and active_model != fallback_model:
                print(f"[rag_stream_answer] model {active_model} not found, fallback to {fallback_model}: {exc}")
                active_model = fallback_model
                chunk_stream = None
                continue
            raise

        yield event, answer_delta


def generate_model_stream(state, web, model_name, messages, streaming_flag=False, is_thinking=False):
    """receive_question 内部函数：按旧逻辑生成 SSE 文本片段。"""
    query = next((message.get("content", "") for message in reversed(messages) if message.get("role") == "user"), "")
    if is_internal_prompt_request(query):
        state.answer_content = SENSITIVE_ERROR_MESSAGE
        yield sse_data(SENSITIVE_ERROR_MESSAGE)
        return

    if streaming_flag:
        yield sse_data("zxl")

    answer_content = ""

    try:
        if model_name in {"spark", cfg["qa_models"]["spark"]["model_name"]}:
            chunk_stream = stream_spark_answer(messages)
        else:
            chunk_stream = _stream_with_fallback(model_name, messages, is_thinking)

        for event, answer_delta in chunk_stream:
            yield event
            answer_content += answer_delta

        if not answer_content:
            answer_content = EMPTY_MODEL_RESPONSE_MESSAGE
            yield sse_data(answer_content)
        state.answer_content = answer_content
    except Exception as exc:
        traceback.print_exc()
        if getattr(exc, "code", None) == "data_inspection_failed":
            yield sse_data("我们换个话题聊聊吧。")
        else:
            yield sse_data(USER_ERROR_MESSAGE)


def save_receive_question_history(qid, query, q_history, state):
    """Persist in-memory and SQL history after a streamed answer completes."""
    full_answer = state.answer_content.replace(STREAM_NEWLINE, "\n").replace(STREAM_SPACE, " ")
    q_history.append({"role": "assistant", "content": full_answer})
    qa_pair = [{"query": query, "answer": full_answer}]
    kdzn_history.add_or_update_user_qa(qid, q_history[-2:])
    kdzn_history.remove_old_users()
    QA_history.add_or_update_user_qa(qid, qa_pair)
    QA_history.remove_old_users()
    update_sql_history(qid, QA_history.get_user_qa_history(qid))


def start_receive_question_worker(event_queue, state, model_choose, q_history, qid, query):
    """Run model streaming in a background thread and always close the SSE queue."""
    def worker():
        answer_finished = False
        try:
            model_llm = get_model(model_choose)
            is_thinking = is_thinking_selection(model_choose)
            for event in generate_model_stream(state, False, model_llm, q_history, is_thinking=is_thinking):
                event_queue.put(event)
            answer_finished = True
        except Exception as exc:
            traceback.print_exc()
            event_queue.put(sse_data(USER_ERROR_MESSAGE))
        finally:
            event_queue.put(None)

        if qid and answer_finished and state.answer_content:
            save_receive_question_history(qid, query, q_history, state)

    threading.Thread(target=worker, daemon=True).start()


def start_direct_question_worker(event_queue, state, model_choose, messages, qid, query):
    def worker():
        try:
            model_llm = get_model(model_choose)
            is_thinking = is_thinking_selection(model_choose)
            for event in generate_model_stream(state, False, model_llm, messages, is_thinking=is_thinking):
                event_queue.put(event)
        except Exception as exc:
            traceback.print_exc()
            event_queue.put(sse_data(USER_ERROR_MESSAGE))
        finally:
            event_queue.put(None)

        if not state.answer_content:
            return
        answer = state.answer_content.replace(STREAM_NEWLINE, "\n").replace(STREAM_SPACE, " ")
        direct_qa_history.add_or_update_user_qa(
            qid,
            [
                {"role": "user", "content": query},
                {"role": "assistant", "content": answer},
            ],
        )
        direct_qa_history.remove_old_users()

    threading.Thread(target=worker, daemon=True).start()


async def handle_direct_question(request: Request):
    try:
        query_data = await request.json()
    except Exception as exc:
        return JSONResponse({"status": "error", "message": f"请求体 JSON 解析失败: {exc}"}, status_code=400)

    qid = str(query_data.get("qid") or "").strip()
    query = str(query_data.get("query") or "").strip()
    model_choose = query_data.get("model_choose") or "Auto"
    if not qid or not query:
        return JSONResponse({"status": "error", "message": "qid、query 不能为空"}, status_code=400)

    messages = list(direct_qa_history.get_user_qa_history(qid))
    messages.append({"role": "user", "content": query})
    event_queue = queue.Queue()
    state = SimpleNamespace(reasoning_content="", answer_content="", is_answering=False)
    start_direct_question_worker(event_queue, state, model_choose, messages, qid, query)
    return StreamingResponse(queue_consumer(event_queue, timeout=80), media_type="text/event-stream")


async def handle_receive_question(request: Request):
    """接口 receive_question：接收普通 QA 问题，检索知识库并流式返回模型答案。"""
    try:
        query_data = await request.json()
    except Exception as exc:
        return JSONResponse({"status": "error", "message": f"请求体 JSON 解析失败: {exc}"}, status_code=400)

    userid = query_data.get("userid") or query_data.get("userId")
    qid = query_data.get("qid")
    query = query_data.get("query")
    model_choose = query_data.get("model_choose")
    if not userid or not qid or not query:
        return JSONResponse({"status": "error", "message": "userid、qid、query 不能为空"}, status_code=400)

    try:
        kochatbot = get_kochatbot()
        prompt = kochatbot.koquery2kb(query, userid)
    except Exception as exc:
        return JSONResponse({"status": "error", "message": f"知识库检索失败: {exc}"}, status_code=500)
    event_queue = queue.Queue()
    state = SimpleNamespace(reasoning_content="", answer_content="", is_answering=False)
    q_history = kdzn_history.get_user_qa_history(qid)
    q_history.append({"role": "user", "content": prompt})

    start_receive_question_worker(event_queue, state, model_choose, q_history, qid, query)
    return StreamingResponse(queue_consumer(event_queue, timeout=80), media_type="text/event-stream")
