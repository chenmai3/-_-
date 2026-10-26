import json
import re
import threading
import time
from dataclasses import asdict, dataclass
from typing import Any, Callable, Optional


def _extract_json_object(raw: Any) -> dict:
    if isinstance(raw, dict):
        return raw
    text = str(raw or "").strip()
    if not text:
        return {}
    fenced = re.search(r"```(?:json)?\s*(\{.*?\})\s*```", text, flags=re.DOTALL | re.IGNORECASE)
    if fenced:
        text = fenced.group(1)
    start = text.find("{")
    if start < 0:
        return {}
    try:
        value, _ = json.JSONDecoder().raw_decode(text[start:])
        return value if isinstance(value, dict) else {}
    except (TypeError, ValueError, json.JSONDecodeError):
        return {}


def _split_items(value: Any) -> list[str]:
    if value is None:
        return []
    if isinstance(value, (list, tuple, set)):
        values = value
    else:
        values = re.split(r"[；;\n]+", str(value))
    result = []
    for item in values:
        text = re.sub(r"^\s*\d+[.、]\s*", "", str(item)).strip(" 。；;\t\r\n")
        if text and text != "无" and text not in result:
            result.append(text)
    return result


def _fallback_split(text: str) -> dict[str, str]:
    text = text.strip()
    question_match = list(re.finditer(r"[^。！？!?]*[？?]", text))
    if question_match:
        match = question_match[-1]
        statement = (text[:match.start()] + text[match.end():]).strip()
        question = match.group(0).strip()
    elif re.search(r"谁|什么|哪|几|是否|怎么|如何|为何|为什么", text):
        statement, question = "", text
    else:
        statement, question = text, ""

    if statement and question and re.match(r"^[他她其]的", question):
        names = re.findall(r"([\u4e00-\u9fff]{2,4})(?=是|的|生于|出生)", statement)
        if names:
            question = re.sub(r"^[他她其](?=的)", names[-1], question, count=1)
    return {"chenShu": statement, "wenTi": question}


def _normalize_triples(value: Any) -> list[list[str]]:
    triples = []
    for item in value or []:
        if isinstance(item, dict):
            row = [item.get("head"), item.get("relation"), item.get("tail")]
        elif isinstance(item, (list, tuple)):
            row = list(item[:3])
        else:
            continue
        if len(row) != 3:
            continue
        normalized = [str(part or "").strip() for part in row]
        if all(normalized) and normalized not in triples:
            triples.append(normalized)
    return triples


def _fallback_triples(text: str) -> list[list[str]]:
    triples = []
    patterns = (
        r"(?P<head>[\u4e00-\u9fff]{2,8})的(?P<relation>父亲|母亲|儿子|女儿|妻子|丈夫|兄弟|姐妹)是(?P<tail>[^，。；;]+)",
        r"(?P<head>[\u4e00-\u9fff]{2,8})是(?P<tail>[^，。；;]+)",
    )
    for sentence in _split_items(re.sub(r"[。]", "；", text)):
        for pattern in patterns:
            match = re.search(pattern, sentence)
            if not match:
                continue
            relation = match.groupdict().get("relation") or "是"
            row = [match.group("head"), relation, match.group("tail").strip()]
            if row not in triples:
                triples.append(row)
            break
    return triples


class FamilyAuxiliaryService:
    def __init__(self, llm: Optional[Callable[[str], str]] = None):
        self._llm = llm
        self._default_llm = None

    def _ask(self, prompt: str) -> str:
        try:
            if self._llm is not None:
                return self._llm(prompt) or ""
            if self._default_llm is None:
                from ..kdzn_hciqa.engine_dependencies.llm_clients import llm_config

                self._default_llm = llm_config()
            return self._default_llm.qwen2(None, prompt) or ""
        except Exception as exc:
            print(f"[jiapu_qa] auxiliary LLM failed, using deterministic fallback: {exc}")
            return ""

    def split_statement_question(self, text: str) -> dict[str, str]:
        fallback = _fallback_split(text)
        prompt = f"""你是家谱问答文本分析器。将输入分为陈述和问题；若问题中的“他/她/其”可由陈述确定，请替换为明确人名。
只输出 JSON：{{"statement":"...","inquire":"..."}}。
输入：{text}"""
        parsed = _extract_json_object(self._ask(prompt))
        statement = str(parsed.get("statement") or parsed.get("chenShu") or fallback["chenShu"]).strip()
        question = str(parsed.get("inquire") or parsed.get("wenTi") or fallback["wenTi"]).strip()
        return {"chenShu": "" if statement == "无" else statement, "wenTi": "" if question == "无" else question}

    def extract_triples(self, text: str) -> dict[str, list]:
        if not str(text or "").strip():
            return {"tiaoMu": [], "triple": []}
        fallback_items = _split_items(re.sub(r"[。]", "；", text))
        fallback_triples = _fallback_triples(text)
        prompt = f"""你是家谱知识抽取器。把文本拆成独立知识条目，并抽取三元组。
只输出 JSON：{{"items":["条目"],"triples":[["头实体","关系","尾实体"]]}}。
关系未知时使用“？”，不要臆造事实。
文本：{text}"""
        parsed = _extract_json_object(self._ask(prompt))
        items = _split_items(parsed.get("items") or parsed.get("tiaoMu")) or fallback_items
        triples = _normalize_triples(parsed.get("triples") or parsed.get("triple")) or fallback_triples
        return {"tiaoMu": items, "triple": triples}

    def merge_answer(self, statement_items: Any, graph_items: Any, web_items: Any, question: str) -> tuple[str, list[str]]:
        items = []
        for source in (statement_items, graph_items, web_items):
            for item in _split_items(source):
                if item not in items:
                    items.append(item)
        if not question:
            question = "请综合以上信息。"
        numbered = "\n".join(f"{index}. {item}" for index, item in enumerate(items, 1))
        prompt = f"""你是家谱问答助手。严格依据知识条目回答问题；信息不足时明确说明，不得编造。
只输出 JSON：{{"answer":"回答","useful_items":["实际使用的原始条目"]}}。
知识条目：
{numbered or '无'}
问题：{question}"""
        parsed = _extract_json_object(self._ask(prompt))
        answer = str(parsed.get("answer") or parsed.get("回答") or "").strip()
        useful = _split_items(parsed.get("useful_items") or parsed.get("有用的知识条目"))
        useful = [item for item in useful if item in items]
        if not answer:
            if items:
                answer = "根据现有信息，" + "；".join(items) + "。"
                useful = useful or items
            else:
                answer = "现有知识不足，无法可靠回答该问题。"
        return answer, useful

    def merge_multi_answer(self, statement_items: Any, graph_items: Any, web_items: Any, history: list[dict]) -> tuple[list[dict], list[str]]:
        messages = [dict(item) for item in history]
        question = next((str(item.get("content")) for item in reversed(messages) if item.get("role") == "user"), "")
        answer, useful = self.merge_answer(statement_items, graph_items, web_items, question)
        messages.append({"role": "assistant", "content": answer})
        return messages, useful


class NormalAnswerService:
    def __init__(self, llm_factory: Optional[Callable[[], Any]] = None):
        self._llm_factory = llm_factory
        self._llm = None

    def _get_llm(self):
        if self._llm is None:
            if self._llm_factory is None:
                from ..kdzn_hciqa.engine_dependencies.llm_clients import llm_config

                self._llm = llm_config()
            else:
                self._llm = self._llm_factory()
        return self._llm

    async def stream(self, history: list[dict]):
        question = next(
            (
                str(item.get("content"))
                for item in reversed(history)
                if item.get("role") == "user" and item.get("content")
            ),
            "",
        )
        if not question and history and history[-1].get("content"):
            question = str(history[-1]["content"])
        if not question:
            return

        messages = [{"role": "user", "content": question}]
        async for chunk in self._get_llm().qwen2_stream(messages):
            if chunk:
                yield f"data: {chunk}\n\n"


@dataclass
class FamilySessionState:
    session_id: str
    stage: int
    status: str
    message: str
    updated_at: float


class FamilySessionStateStore:
    def __init__(self):
        self._lock = threading.RLock()
        self._states: dict[str, FamilySessionState] = {}
        self._latest_session_id = ""

    def _set(self, session_id: str, stage: int, status: str, message: str) -> dict:
        session_id = str(session_id or "default")
        state = FamilySessionState(session_id, stage, status, message, time.time())
        with self._lock:
            cutoff = state.updated_at - 86400
            expired = [key for key, value in self._states.items() if value.updated_at < cutoff]
            for key in expired:
                self._states.pop(key, None)
            self._states[session_id] = state
            self._latest_session_id = session_id
        return asdict(state)

    def start(self, session_id: str) -> dict:
        return self._set(session_id, 0, "processing", "正在处理")

    def complete(self, session_id: str, message: str = "处理完成") -> dict:
        return self._set(session_id, 1, "completed", message)

    def fail(self, session_id: str, message: str) -> dict:
        return self._set(session_id, -1, "failed", message)

    def get(self, session_id: str = "") -> dict:
        with self._lock:
            key = str(session_id or self._latest_session_id or "default")
            state = self._states.get(key)
            if state is None:
                return asdict(FamilySessionState(key, 1, "idle", "暂无进行中的任务", time.time()))
            return asdict(state)
