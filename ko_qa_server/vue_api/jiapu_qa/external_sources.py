import asyncio
import json
import logging
import os
import ssl
from typing import Any

import httpx

from ..kdzn_hciqa.engine_dependencies.web_search import web_search_DDG, web_search_dashscope
from ..kdzn_hciqa.shared import Result


logger = logging.getLogger("uvicorn.error")
HPT_POLL_ATTEMPTS = max(1, int(os.getenv("HPT_POLL_ATTEMPTS", "36")))
HPT_POLL_INTERVAL = max(0.1, float(os.getenv("HPT_POLL_INTERVAL", "5")))
HPT_HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
        "(KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
    ),
    "Accept": "*/*",
    "Connection": "close",
}


HPT_SUBMIT_URL = os.getenv(
    "HPT_SUBMIT_URL",
    "https://www.zhonghuapu.com/index.php/datamgr/getHuaPUDaMoXingAnswer",
)
HPT_RESULT_URL = os.getenv(
    "HPT_RESULT_URL",
    "https://www.zhonghuapu.com/index.php/datamgr/getHuaPuTongAnswerByID",
)
HPT_CANCEL_URL = os.getenv(
    "HPT_CANCEL_URL",
    "https://www.zhonghuapu.com/index.php/datamgr/deleteHuaPuTongQueryByID",
)


def _escape_control_chars_in_strings(text: str) -> str:
    output = []
    in_string = False
    escaped = False
    for char in text:
        if in_string and char in "\r\n":
            output.append("\\n")
            escaped = False
            continue
        output.append(char)
        if escaped:
            escaped = False
        elif char == "\\" and in_string:
            escaped = True
        elif char == '"':
            in_string = not in_string
    return "".join(output)


def parse_mixed_json(text: str) -> dict:
    value = str(text or "").strip()
    start = value.find("{")
    if start < 0:
        raise ValueError("响应中未找到 JSON")
    candidate = _escape_control_chars_in_strings(value[start:])
    try:
        parsed, _ = json.JSONDecoder().raw_decode(candidate)
    except json.JSONDecodeError as exc:
        raise ValueError(f"响应 JSON 解析失败: {exc}") from exc
    if not isinstance(parsed, dict):
        raise ValueError("响应 JSON 不是对象")
    return parsed


def parse_name_list(raw: Any) -> list[str]:
    if isinstance(raw, str):
        try:
            raw = json.loads(raw)
        except json.JSONDecodeError:
            raw = [raw]
    if not isinstance(raw, (list, tuple, set)):
        raw = [raw] if raw else []
    return [str(item).strip() for item in raw if str(item or "").strip()]


class HuaPuTongClient:
    def __init__(self, timeout=30.0):
        self.timeout = timeout

    def _new_client(self):
        # Match the legacy site's TLS adapter while retaining certificate checks.
        context = ssl.create_default_context()
        context.minimum_version = ssl.TLSVersion.TLSv1_2
        context.set_ciphers("DEFAULT@SECLEVEL=1")
        return httpx.AsyncClient(
            timeout=self.timeout, headers=HPT_HEADERS, follow_redirects=True,
            transport=httpx.AsyncHTTPTransport(verify=context, retries=3),
        )

    async def submit(self, payload: dict, client=None) -> str:
        if client is None:
            async with self._new_client() as session:
                return await self.submit(payload, client=session)
        response = await client.post(HPT_SUBMIT_URL, data=payload)
        response.raise_for_status()
        data = parse_mixed_json(response.text)
        query_id = str(data.get("query_id") or "").strip()
        if not query_id:
            detail = data.get("detail") or data.get("errorMessage") or data.get("msg")
            reason = json.dumps(detail, ensure_ascii=False)[:500] if detail else "响应未包含任务 ID"
            raise ValueError(f"华谱通未返回 query_id：{reason}")
        logger.info("[华谱通] 任务已提交 query_id=%s", query_id)
        return query_id

    async def get_result(self, query_id: str, client=None) -> dict:
        if not str(query_id or "").strip():
            raise ValueError("queryID 不能为空")
        if client is None:
            async with self._new_client() as session:
                return await self.get_result(query_id, client=session)
        response = await client.get(HPT_RESULT_URL, params={"queryID": query_id})
        response.raise_for_status()
        return parse_mixed_json(response.text)

    async def cancel(self, query_id: str, client=None) -> None:
        if client is None:
            async with self._new_client() as session:
                return await self.cancel(query_id, client=session)
        response = await client.get(HPT_CANCEL_URL, params={"queryID": query_id})
        response.raise_for_status()

    async def ask(
        self, payload: dict, attempts=HPT_POLL_ATTEMPTS, interval=HPT_POLL_INTERVAL
    ) -> tuple[str, dict]:
        # PHPSESSID is set when submitting. Keep the same per-task session for
        # polling/cancellation, without sharing cookies between users' tasks.
        async with self._new_client() as client:
            query_id = await self.submit(payload, client=client)
            for attempt in range(attempts):
                answer = await self.get_result(query_id, client=client)
                logger.info(
                    "[华谱通] query_id=%s 轮询=%s/%s flag=%s 答案字符数=%s",
                    query_id, attempt + 1, attempts, answer.get("flag"),
                    len(str(answer.get("ans") or "")),
                )
                if str(answer.get("flag", "0")) != "0":
                    return query_id, answer
                if attempt + 1 < attempts:
                    await asyncio.sleep(interval)
            try:
                await self.cancel(query_id, client=client)
            except Exception:
                logger.warning("[华谱通] 超时任务清理失败 query_id=%s", query_id, exc_info=True)
            raise TimeoutError(
                f"华谱通任务 {query_id} 在 {attempts} 次查询后仍未完成（flag=0），"
                "外部服务尚未返回答案，请检查华谱通任务处理服务"
            )


hpt_client = HuaPuTongClient()


def result(response=None, status=200, error_message=None):
    return dict(Result(response=response, status=status, errorMessage=error_message))


async def handle_get_by_web(payload: dict):
    names = parse_name_list(payload.get("name2web"))
    statement = str(payload.get("chenShu") or "").strip()
    query = " ".join([*names[:2], statement]).strip()
    if not query:
        return result(status=400, error_message="chenShu、name2web 不能同时为空")
    try:
        content = await asyncio.to_thread(web_search_dashscope, query)
        if not content:
            content = await asyncio.to_thread(web_search_DDG, query)
        return result(response={"web_content": content or "无"})
    except Exception as exc:
        return result(status=500, error_message=f"网页检索失败: {exc}")


async def handle_hpt_answer(payload: dict):
    try:
        query_id, answer = await hpt_client.ask(payload)
        return result(
            response={
                "answer": answer,
                "gotAns": True,
                "query_id": query_id,
                "name_list": parse_name_list(answer.get("name_list")),
            }
        )
    except Exception as exc:
        logger.warning("[华谱通] 外部查询失败: %s", exc, exc_info=True)
        return result(
            response={"answer": "", "gotAns": False, "name_list": []},
            status=502,
            error_message=f"华谱通请求失败: {exc}",
        )


async def handle_hpt_result(query_id: str):
    try:
        answer = await hpt_client.get_result(query_id)
        got_answer = str(answer.get("flag", "0")) != "0"
        return result(
            response={
                "answer": answer,
                "gotAns": got_answer,
                "query_id": query_id,
                "name_list": parse_name_list(answer.get("name_list")),
            }
        )
    except Exception as exc:
        return result(status=502, error_message=f"华谱通结果查询失败: {exc}")
