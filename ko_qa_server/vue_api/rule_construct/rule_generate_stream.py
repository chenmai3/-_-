import json
import queue
import re
import threading
import time

from openai import OpenAI

from .common import connect_to_db, load_config, sse_text, stream_from_queue
from .rule_database import get_label_with_userid
from .rule_path_core import (
    fuzzy_match_paths_2,
    generate_cypher_query,
    generate_rule_path_cypher,
    query,
    query_rule,
    replace_with_literal,
)


def get_human(get_in_4_simi, rule_path, rule_name, input_entity, output_entity):
    # rule_generate 接口内部函数：调用大模型把 Cypher 规则转成可读说明。
    cfg = load_config()
    client = OpenAI(
        api_key=cfg["small_models"]["qwen"]["api_key"],
        base_url=cfg["small_models"]["qwen"].get("base_url", "https://dashscope.aliyuncs.com/compatible-mode/v1"),
    )
    model_name = cfg["small_models"]["qwen"].get("model", "deepseek-v3")
    messages = [{
        "role": "system",
        "content": (
            "请根据下面的规则入口、推理规则、规则名、入口实体、出口实体，"
            "将规则入口和推理规则这两条 match 语句转成通俗易懂的逻辑人话。\n"
            f"规则名：{rule_name}\n入口实体：{input_entity}\n出口实体：{output_entity}\n"
            f"规则入口：{get_in_4_simi}\n推理规则：{rule_path}\n"
            "回答格式如下：\n规则入口：\n推理规则："
        ),
    }]
    response = client.chat.completions.create(
        model=model_name,
        messages=messages,
        temperature=0.1,
        stream=False,
    )
    text = response.choices[0].message.content
    match = re.search(r"规则入口：\s*(.*?)\s*推理规则：\s*(.*)", text, re.DOTALL)
    if not match:
        return "", ""
    return match.group(1).strip(), match.group(2).strip()


def resolve_theme_label(selected_main_scenario: str, scene: str):
    connection = connect_to_db()
    if not connection:
        raise RuntimeError("数据库连接失败")
    try:
        theme_label = get_label_with_userid(connection, selected_main_scenario, scene)
        if selected_main_scenario == "家谱问答":
            return "huaputong"
        if selected_main_scenario == "轨交诊断":
            return "kedazhineng"
        if not theme_label:
            raise RuntimeError("未找到主题对应的图谱标签")
        return theme_label
    finally:
        connection.close()


def generate_one_rule(payload: dict, event_queue: queue.Queue):
    # rule_generate 接口内部主流程：入口实体召回 -> 入口规则 -> 出口实体匹配 -> 推理规则 -> 人话说明。
    scene = payload["selectedScenario"]
    input_entity = payload["input_entityName"]
    output_entity = payload["output_entityName"]
    rule_name = payload["rule_name"]
    selected_main_scenario = payload.get("selectedMainScenario", "轨交诊断")

    theme_label = resolve_theme_label(selected_main_scenario, scene)

    event_queue.put(sse_text("正在查询子图..."))
    time.sleep(0.1)
    entry_paths, _ = query_rule(theme_label, selected_main_scenario, scene, input_entity)
    if not entry_paths:
        event_queue.put(sse_text("入口实体匹配为空！"))
        return

    event_queue.put(sse_text("正在生成规则入口..."))
    time.sleep(0.1)
    get_in_4_simi = generate_cypher_query(selected_main_scenario, theme_label, entry_paths, input_entity, scene)
    if not get_in_4_simi:
        event_queue.put(sse_text("入口实体未在路径中"))
        return

    event_queue.put(sse_text("正在匹配出口实体..."))
    time.sleep(0.1)
    formatted_paths, _ = query(theme_label, selected_main_scenario, scene, input_entity)
    matched_paths = fuzzy_match_paths_2(formatted_paths, output_entity)
    if not matched_paths:
        event_queue.put(sse_text("出口实体匹配为空！"))
        return

    event_queue.put(sse_text("正在生成推理规则..."))
    time.sleep(0.1)
    rule_path = generate_rule_path_cypher(selected_main_scenario, theme_label, matched_paths, input_entity)
    rule_path = replace_with_literal(rule_path)
    if not rule_path:
        event_queue.put(sse_text("出口实体未在路径中"))
        return

    rule_entry_human, inference_rule_human = get_human(
        get_in_4_simi, rule_path, rule_name, input_entity, output_entity
    )
    result = {
        "getIn4simi": get_in_4_simi,
        "rule_path": rule_path,
        "rule_entry_human": rule_entry_human,
        "inference_rule_human": inference_rule_human,
    }
    event_queue.put(sse_text("生成完成！"))
    event_queue.put(sse_text(json.dumps(result, ensure_ascii=False)))


async def handle_rule_generate(payload: dict):
    q = queue.Queue()

    def worker():
        try:
            generate_one_rule(payload, q)
        except Exception as exc:
            q.put(sse_text(f"错误: {exc}"))
        finally:
            q.put(None)

    threading.Thread(target=worker, daemon=True).start()
    return stream_from_queue(q)
