"""KO graph QA: query the legacy ownthink graph, independently of family QA."""

import itertools
import json
import logging
import queue
import re
import threading
from types import SimpleNamespace

from ..common.neo4j_client import query_new_neo4j
from ..kdzn_hciqa.engine_dependencies.graph_rule_queries.neo4j_def import (
    _node_name, _record_path, _relation_name,
)
from ..kdzn_hciqa.qa_answer.prompt_security import is_internal_prompt_request
from ..kdzn_hciqa.qa_answer.rag_stream_answer import generate_model_stream, get_llm
from ..kdzn_hciqa.shared import (
    SENSITIVE_ERROR_MESSAGE, get_model, is_thinking_selection, sse_error, stream_response,
)
from .domain import _extract_json_object


logger = logging.getLogger("uvicorn.error")
GRAPH_LABELS = ("ownthink", "huaputong")


def extract_entities(question, history):
    # Common relationship questions need no extra model round trip.
    pair = re.match(
        r"^(?:请问|请问一下)?\s*(.+?)(?:和|与|跟)(.+?)(?:是什么关系|有什么关系|的关系|之间.*关系)[？?。\s]*$",
        question,
    )
    if pair:
        return [name.strip(' “”？?') for name in pair.groups()]
    prompt = (
        '抽取用户问题中需要从知识图谱检索的实体名称（人物、事物等），'
        '结合前面对话消解代词，不要把关系或“谁”作为实体，不要编造。'
        '只输出 JSON：{"entities":["实体名称"]}。\n'
        f'前面对话：{json.dumps(history[-6:-1], ensure_ascii=False)}\n问题：{question}'
    )
    parsed = _extract_json_object(get_llm().qwen2(None, prompt))
    values = parsed.get("entities", [])
    if not isinstance(values, list):
        return []
    return list(dict.fromkeys(str(value).strip() for value in values if str(value).strip()))[:4]


def format_paths(records):
    paths = []
    for record in records:
        path = _record_path(record)
        if path is None or not path.nodes:
            continue
        nodes = list(path.nodes)
        text = _node_name(nodes[0])
        for index, relationship in enumerate(path.relationships):
            relation = _relation_name(relationship)
            following = _node_name(nodes[index + 1])
            if relationship.start_node == nodes[index]:
                text += f"-{relation}->{following}"
            else:
                text += f"<-{relation}-{following}"
        if text not in paths:
            paths.append(text)
    return paths


def retrieve_graph(entities):
    """Use the same Neo4j connection and labels as the legacy KO path queries."""
    properties = []
    paths = []
    for label in GRAPH_LABELS:
        rows = query_new_neo4j(
            f"MATCH (n:{label}) WHERE n.name IN $entities "
            "RETURN n.name AS name, properties(n) AS properties LIMIT 20",
            parameters={"entities": entities}, timeout=15, kg="jiapu",
        )
        found = list(dict.fromkeys(row["name"] for row in rows))
        properties.extend({"name": row["name"], "properties": row["properties"]} for row in rows)
        for head, tail in itertools.combinations(found[:4], 2):
            records = query_new_neo4j(
                f"MATCH (a:{label} {{name: $head}}), (b:{label} {{name: $tail}}) "
                "MATCH p=shortestPath((a)-[*1..5]-(b)) RETURN p LIMIT 5",
                parameters={"head": head, "tail": tail}, timeout=15, kg="jiapu",
            )
            paths.extend(format_paths(records))
        if not paths:
            for name in found[:2]:
                records = query_new_neo4j(
                    f"MATCH p=(a:{label} {{name: $name}})-[r]-(b:{label}) RETURN p LIMIT 10",
                    parameters={"name": name}, timeout=15, kg="jiapu",
                )
                paths.extend(format_paths(records))
        if found:
            break
    return {"entities": properties, "paths": list(dict.fromkeys(paths))}


def event(name, payload):
    # Include the kind in data so deployed Java gateways which strip SSE
    # event/newline fields still preserve the distinction from answer text.
    body = {"type": name, **payload}
    return f"data: {json.dumps(body, ensure_ascii=False, default=str)}\n\n"


async def start_ko_graph_stream(data, history, question):
    event_queue = queue.Queue()

    def worker():
        try:
            if is_internal_prompt_request(question):
                event_queue.put(f"data: {SENSITIVE_ERROR_MESSAGE}\n\n")
                return
            event_queue.put(event("status", {"message": "正在查询KO知识图谱..."}))
            entities = extract_entities(question, history)
            evidence = retrieve_graph(entities) if entities else {"entities": [], "paths": []}
            logger.info("[KO图谱问答] 实体=%s 匹配节点数=%s 路径数=%s", entities,
                        len(evidence["entities"]), len(evidence["paths"]))
            event_queue.put(event("paths", {"paths": evidence["paths"]}))
            event_queue.put(event("status", {"message": "正在根据图谱证据生成回答..."}))
            prompt = (
                '你是KO图谱问答助手。根据以下实际检索到的Neo4j节点属性和关系路径回答问题。'
                '路径中的箭头表示关系方向。只将检索证据支持的内容称为图谱知识；'
                '未找到连接路径时说明本次检索未找到，不能断言现实中没有关系。'
                '如果资料不足，明确说明不足；不要虚构人物家谱背景、查询结果或页面操作。'
                '请使用Markdown，先回答问题，再简要列出相关证据。\n'
                f'图谱检索结果：{json.dumps(evidence, ensure_ascii=False, default=str)[:24000]}\n'
                f'用户问题：{question}'
            )
            messages = [dict(item) for item in history[-12:-1] if item.get("role") in {"user", "assistant"}]
            messages.append({"role": "user", "content": prompt})
            selection = data.get("model_choose") or "Auto"
            state = SimpleNamespace(answer_content="")
            for chunk in generate_model_stream(
                state, False, get_model(selection), messages,
                is_thinking=is_thinking_selection(selection),
            ):
                event_queue.put(chunk)
        except Exception:
            logger.exception("[KO图谱问答] 查询或回答失败")
            event_queue.put(sse_error("KO图谱查询或回答失败，请检查后端日志后重试。"))
        finally:
            event_queue.put(None)

    threading.Thread(target=worker, daemon=True).start()
    response = stream_response(event_queue, timeout=80)
    response.headers["Cache-Control"] = "no-cache, no-transform"
    response.headers["X-Accel-Buffering"] = "no"
    return response
