from openai import OpenAI
import os
import aiohttp
import asyncio
import threading
import queue
import time
import json
from queue import Queue
from ...shared import load_config


def get_standard_llm_config():
    cfg = load_config()
    qwen_config = cfg.get("small_models", {}).get("qwen", {})
    return {
        "api_key": os.getenv("STANDARD_DOC_LLM_API_KEY", qwen_config.get("api_key", "")),
        "base_url": os.getenv("STANDARD_DOC_LLM_BASE_URL", qwen_config.get("base_url", "")),
        "model": (os.getenv("STANDARD_DOC_LLM_MODEL") or qwen_config.get("model")
                  or qwen_config.get("qwen2.5_model_name") or qwen_config.get("qwen2_model_name") or "qwen-max"),
        "temperature": float(os.getenv("STANDARD_DOC_LLM_TEMPERATURE", qwen_config.get("temperature", 0.0))),
        "top_p": float(os.getenv("STANDARD_DOC_LLM_TOP_P", 0.8)),
        "max_tokens": int(os.getenv("STANDARD_DOC_LLM_MAX_TOKENS", 4096)),
    }


def get_standard_llm_client():
    llm_config = get_standard_llm_config()
    return OpenAI(api_key=llm_config["api_key"], base_url=llm_config["base_url"], timeout=120, max_retries=1)


class ProgressChannel:
    def __init__(self):
        self.queue = Queue()
        self.done = False
        self.result = None

    def emit(self, section: str, content: str):
        # 在每条流程消息后面加一个“流式换行”占位符
        # content_with_break = content + "StReAmNeWlInE"
        # 如果你想空一行，就用 "StReAmNeWlInEStReAmNeWlInE"
        # content_with_break = content + "StReAmNeWlInEStReAmNeWlInE"

        self.queue.put({
            "section": section,
            "content": content
        })


def chat(messages, stream=True, model=None):
    llm_config = get_standard_llm_config()
    client = get_standard_llm_client()
    try:
        response = client.chat.completions.create(
            model=model or llm_config["model"],
            messages=messages,
            stream=stream,
            temperature=llm_config["temperature"],
            top_p=llm_config["top_p"],
            max_tokens=llm_config["max_tokens"],
        )
        if stream:
            res = []
            for chunk in response:
                if chunk.choices[0].delta.content:
                    delta = chunk.choices[0].delta.content
                    print(delta, end="", flush=True)
                    res.append(delta)
            print('\n\n')
            return "".join(res).strip()
        else:
            content = response.choices[0].message.content
            print(content, end='\n\n')
            return content.strip()
    except Exception as e:
        print(f"\n[Error] {e}")
        return None


async def _chat_limited(
    session,
    messages,
    task_name=None,
    session_id=None,
    model=None,
    status_section=None,      # 新增：这个阶段对应的 section
    progress_cb=None,        # 新增：进度回调
):
    llm_config = get_standard_llm_config()
    url = f"{llm_config['base_url'].rstrip('/')}/chat/completions"
    payload = {
        "model": model or llm_config["model"],
        "messages": messages,
        "stream": False,
        "temperature": llm_config["temperature"],
        "top_p": llm_config["top_p"],
        "max_tokens": llm_config["max_tokens"],
    }
    headers = {
        "Authorization": f"Bearer {llm_config['api_key']}",
        "Content-Type": "application/json"
    }
    try:
        msg1 = f"✅ {task_name} [章节 {session_id + 4}] 开始对话"
        print(msg1)
        if progress_cb is not None and status_section is not None:
            progress_cb(status_section, msg1)

        async with session.post(url, headers=headers, json=payload) as resp:
            if resp.status != 200:
                msg_err = f"⚠️ {task_name} [章节 {session_id + 4}] 模型请求失败（HTTP {resp.status}）"
                print(msg_err)
                if progress_cb is not None and status_section is not None:
                    progress_cb(status_section, msg_err)
                raise RuntimeError(msg_err)

            result = await resp.json()
            content = result["choices"][0]["message"]["content"]

        msg2 = f"✅ {task_name} [章节 {session_id + 4}] 回答完毕"
        print(msg2)
        if progress_cb is not None and status_section is not None:
            progress_cb(status_section, msg2)

        return content.strip()

    except Exception as e:
        msg_err = f"⚠️ {task_name} [章节 {session_id+ 4}] 模型调用失败，请查看后端日志"
        print(msg_err)
        if progress_cb is not None and status_section is not None:
            progress_cb(status_section, msg_err)
        raise


async def _chat_async(
    messages_list,
    task_name,
    max_concurrency=10,
    model=None,
    status_section=None,      # 新增
    progress_cb=None,        # 新增
):
    semaphore = asyncio.Semaphore(max_concurrency)
    async with aiohttp.ClientSession(timeout=aiohttp.ClientTimeout(total=180)) as session:
        async def run_task(i, messages):
            async with semaphore:
                return await _chat_limited(
                    session,
                    messages,
                    task_name=task_name,
                    session_id=i,
                    model=model,
                    status_section=status_section,
                    progress_cb=progress_cb,
                )

        tasks = [run_task(i, messages_list[i]) for i in range(len(messages_list))]
        results = await asyncio.gather(*tasks)
        return results


def chat_async(
    messages_list,
    task_name,
    max_concurrency=10,
    model=None,
    status_section=None,     # 新增
    progress_cb=None,       # 新增
):
    return asyncio.run(
        _chat_async(
            messages_list,
            task_name,
            max_concurrency=max_concurrency,
            model=model,
            status_section=status_section,
            progress_cb=progress_cb,
        )
    )


def main():
    messages_list = [
        [{"role": "user", "content": "写一首诗"}],
        [{"role": "user", "content": "你好"}],
        [{"role": "user", "content": "讲个笑话"}],
    ]
    results = chat_async(messages_list, 'a')
    # 并发执行多个对话任务
    for result in results:
        print(result)
    results = chat_async(messages_list, 'b')
    # 并发执行多个对话任务
    for result in results:
        print(result)


def run_stage_with_progress(messages_list, task_name, status_section,
                            model=None, max_concurrency=10):
    """
    一个生成器：
      - 后台线程中执行 chat_async（并发多轮 LLM 调用）
      - 期间所有进度通过 ProgressChannel.queue 流式产出
      - 结束后 return 最终 results（配合 `yield from` 使用）
    """
    progress = ProgressChannel()

    failures = []

    def worker():
        try:
            progress.result = chat_async(
                messages_list,
                task_name=task_name,
                max_concurrency=max_concurrency,
                model=model,
                status_section=status_section,
                progress_cb=progress.emit,
            )
        except Exception as exc:
            failures.append(exc)
        finally:
            progress.done = True

    # 启动后台线程
    threading.Thread(target=worker, daemon=True).start()

    # 主线程不断消费队列，并 yield 给前端（SSE）
    while not progress.done or not progress.queue.empty():
        try:
            msg = progress.queue.get(timeout=0.1)
        except queue.Empty:
            continue

        # msg 形如 {"section": "dagang(zhengwen)_status", "content": "✅ 正文生成 ..."}
        payload = {
            "section": status_section,
            "content": msg["content"],
        }
        yield f"data: {json.dumps(payload, ensure_ascii=False)}\n\n"
        time.sleep(0.02)  # 打字效果，可选

    # 把结果返回给上层（要用 `yield from` 接）
    if failures:
        raise failures[0]
    return progress.result

if __name__ == "__main__":
    main()
