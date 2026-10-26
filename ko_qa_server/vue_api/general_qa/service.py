import asyncio
import ipaddress
import socket
from functools import lru_cache
from typing import Callable, Optional
from urllib.parse import urljoin, urlparse

import httpx
from bs4 import BeautifulSoup

from ..common.paths import USER_VECTOR_STORES_ROOT
from ..common.vector_assets import inspect_vector_store
from ..kdzn_hciqa.engine_dependencies.llm_clients import llm_config
from ..kdzn_hciqa.shared import Result, get_kochatbot


MAX_WEB_BYTES = 2 * 1024 * 1024
MAX_WEB_TEXT = 30000


def knowledge_base_assets_exist(user_id: str) -> bool:
    root = USER_VECTOR_STORES_ROOT / str(user_id)
    return inspect_vector_store(root).compatible and (root / "index").is_dir()


def validate_public_http_url(url: str) -> str:
    parsed = urlparse(str(url or "").strip())
    if parsed.scheme not in {"http", "https"} or not parsed.hostname:
        raise ValueError("url 必须是有效的 http/https 公网地址")

    try:
        addresses = {item[4][0] for item in socket.getaddrinfo(parsed.hostname, parsed.port)}
    except socket.gaierror as exc:
        raise ValueError(f"url 域名无法解析: {parsed.hostname}") from exc

    for address in addresses:
        ip = ipaddress.ip_address(address)
        if not ip.is_global:
            raise ValueError("不允许访问本机或内网地址")
    return parsed.geturl()


def extract_web_text(content: bytes, content_type: str = "") -> str:
    text = content.decode("utf-8", errors="ignore")
    if "html" not in content_type.lower() and "<html" not in text[:500].lower():
        return " ".join(text.split())[:MAX_WEB_TEXT]

    soup = BeautifulSoup(text, "html.parser")
    for node in soup(["script", "style", "noscript", "svg"]):
        node.decompose()
    return " ".join(soup.get_text(" ", strip=True).split())[:MAX_WEB_TEXT]


async def fetch_public_web_text(url: str) -> str:
    current_url = str(url or "").strip()
    async with httpx.AsyncClient(timeout=20.0, follow_redirects=False) as client:
        for _ in range(4):
            validate_public_http_url(current_url)
            response = await client.get(
                current_url,
                headers={"User-Agent": "KO-QA/1.0 (+https://ko.zhonghuapu.com)"},
            )
            if response.is_redirect:
                location = response.headers.get("location")
                if not location:
                    raise RuntimeError("网页重定向缺少 Location")
                current_url = urljoin(current_url, location)
                continue
            response.raise_for_status()
            if len(response.content) > MAX_WEB_BYTES:
                raise ValueError("网页内容超过 2 MiB 限制")
            text = extract_web_text(response.content, response.headers.get("content-type", ""))
            if not text:
                raise ValueError("网页中没有可用于问答的文本")
            return text
    raise ValueError("网页重定向次数过多")


@lru_cache(maxsize=1)
def get_general_llm():
    return llm_config()


class GeneralQaService:
    def __init__(
        self,
        llm_factory: Callable = get_general_llm,
        chatbot_factory: Callable = get_kochatbot,
        web_fetcher: Callable = fetch_public_web_text,
    ):
        self._llm_factory = llm_factory
        self._chatbot_factory = chatbot_factory
        self._web_fetcher = web_fetcher

    async def answer(self, prompt: str) -> str:
        return await asyncio.to_thread(self._llm_factory().qwen2, None, prompt)

    async def answer_with_kb(self, prompt: str, user_id: str) -> str:
        retrieval_prompt = await asyncio.to_thread(
            self._chatbot_factory().koquery2kb,
            prompt,
            user_id,
        )
        return await self.answer(retrieval_prompt)

    async def answer_url(self, url: str, prompt: str) -> str:
        page_text = await self._web_fetcher(url)
        grounded_prompt = f"""请严格依据以下网页内容回答问题。网页没有答案时明确说明，不得编造。

网页内容：
{page_text}

问题：{prompt}"""
        return await self.answer(grounded_prompt)


general_qa_service = GeneralQaService()


def result(response=None, status=200, error_message: Optional[str] = None):
    return dict(Result(response=response, status=status, errorMessage=error_message))


async def handle_chat(payload: dict):
    prompt = str(payload.get("prompt") or "").strip()
    if not prompt:
        return result(status=400, error_message="prompt 不能为空")
    try:
        return result(response=await general_qa_service.answer(prompt))
    except Exception as exc:
        return result(status=500, error_message=f"通用问答失败: {exc}")


async def handle_chat2kb(payload: dict):
    prompt = str(payload.get("prompt") or "").strip()
    user_id = str(payload.get("userId") or payload.get("userid") or "").strip()
    if not prompt or not user_id:
        return result(status=400, error_message="prompt、userId 不能为空")
    if not knowledge_base_assets_exist(user_id):
        return result(status=404, error_message=f"用户 {user_id} 的本地知识库尚未构建")
    try:
        answer = await general_qa_service.answer_with_kb(prompt, user_id)
        return result(response={"answer": answer})
    except Exception as exc:
        return result(status=500, error_message=f"本地知识库问答失败: {exc}")


async def handle_chat2url(payload: dict):
    prompt = str(payload.get("prompt") or "").strip()
    url = str(payload.get("url") or "").strip()
    if not prompt or not url:
        return result(status=400, error_message="prompt、url 不能为空")
    try:
        return result(response=await general_qa_service.answer_url(url, prompt))
    except Exception as exc:
        return result(status=500, error_message=f"网页问答失败: {exc}")
