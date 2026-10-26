import json
import queue
import threading

from fastapi import UploadFile
from openai import OpenAI

from .common import (
    connect_to_db,
    cost_str,
    han2pinyin_concat,
    load_config,
    now_ts,
    sse_json,
    sse_text,
    stream_from_queue,
)
from .dependencies.rule_graph_engine import (
    file_rule_parse,
    generate_cypher_path_query,
    read_graph_from_neo4j,
    validate_rules_and_collect,
)
from .rule_database import insert_new_data


def resolve_theme_label(selected_main_scenario: str, user_id: str) -> str:
    # rule_generation/uploadRule 公共函数：沿用旧逻辑生成图谱 label，并保留轨交固定 label。
    theme_label = han2pinyin_concat(selected_main_scenario) + f"_{user_id}"
    if selected_main_scenario == "轨交诊断":
        return "kedazhineng"
    if selected_main_scenario == "家谱问答":
        return "huaputong"
    return theme_label


def qwen_api(messages):
    # uploadRule 接口内部函数：显式指定模型参数调用大模型清洗规则文本。
    cfg = load_config()
    client = OpenAI(
        api_key=cfg["qa_models"]["qwen"]["api_key"],
        base_url=cfg["qa_models"]["qwen"]["base_url"],
    )
    model_name = cfg["qa_models"]["qwen"]["qwenMax"]
    completion = client.chat.completions.create(
        model=model_name,
        messages=messages,
        temperature=0.0,
        stream=False,
    )
    return completion.choices[0].message.content


def save_generated_rules(final_result, selected_main_scenario, scene, theme_label, event_queue):
    # rule_generation 接口内部函数：将自动生成的规则批量保存到数据库。
    connection = connect_to_db()
    if not connection:
        raise RuntimeError("数据库连接失败")
    try:
        insert_count = 0
        for rule_item in final_result:
            rule_data = [
                selected_main_scenario,
                scene,
                rule_item["rule_name"],
                rule_item["rule_path"],
                rule_item["getIn4simi"],
                rule_item.get("rule_name", ""),
                "",
                "",
            ]
            insert_new_data(connection, rule_data, theme_label, scene, selected_main_scenario)
            insert_count += 1
        return insert_count
    finally:
        connection.close()


def run_rule_generation(payload: dict, event_queue: queue.Queue):
    # rule_generation 接口主流程：读取图谱 -> 从路径归纳规则 -> 保存规则。
    total_start = now_ts()
    scene = payload["selectedScenario"]
    selected_main_scenario = payload.get("selectedMainTopic", "轨交诊断")
    user_id = payload["userId"]
    theme_label = resolve_theme_label(selected_main_scenario, user_id)

    event_queue.put(sse_text("正在读取图谱..."))
    success, final_result = read_graph_from_neo4j(event_queue, scene, theme_label)
    if not success:
        event_queue.put(sse_json({"success": False, "error": "图谱读取失败"}))
        return
    if not final_result:
        event_queue.put(sse_json({"success": False, "error": "未生成任何规则"}))
        return

    event_queue.put(sse_text("正在保存规则..."))
    insert_count = save_generated_rules(final_result, selected_main_scenario, scene, theme_label, event_queue)
    event_queue.put(
        sse_json({
            "success": True,
            "message": "规则生成成功",
            "insert_count": insert_count,
            "total_cost": cost_str(total_start),
        })
    )


def build_file_rewrite_prompt(rule_des: str) -> str:
    # uploadRule 接口内部函数：将用户上传的自然语言规则描述清洗为可解析 JSON。
    return f"""
你是一位专业的数据清洗与逻辑结构分析专家。请把下面包含链式逻辑的文本拆成合法 JSON 对象。
Key 是抽象关系描述，不包含实体名；Value 是对应逻辑链条内容，必须保留原文实体。
只输出 JSON，不要 Markdown，不要解释。

待处理文本：
{rule_des}
"""


def normalize_rule_description(response_content: str) -> str:
    parsed = json.loads(response_content)
    if isinstance(parsed, dict):
        return "\n".join([f"{key}: {value}" for key, value in parsed.items()])
    if isinstance(parsed, list):
        return "\n".join([str(item) for item in parsed])
    return str(parsed)


def parse_rule_file_lines(rule_des: str, theme_label: str):
    # uploadRule 接口内部函数：逐行解析候选规则链并去重。
    query_str = f"MATCH (n:{theme_label})-[r]->() WITH DISTINCT type(r) AS relationshipType RETURN relationshipType;"
    rule_results = {}
    existing_chains = set()
    for line in rule_des.splitlines():
        if not line.strip():
            continue
        rule_name, chain, _ = file_rule_parse(query_str, line)
        chain_key = tuple(chain) if chain else ()
        if not chain or chain_key in existing_chains:
            continue
        existing_chains.add(chain_key)
        rule_results[len(rule_results)] = {"rule_name": rule_name, "chain": chain}
    return rule_results


def save_file_rules(rule_results, selected_main_scenario, scene, theme_label, event_queue):
    # uploadRule 接口内部函数：校验文件中解析出的规则并保存。
    connection = connect_to_db()
    if not connection:
        raise RuntimeError("数据库连接失败")
    insert_count = 0
    try:
        get_in_4_simi = f"MATCH (n:`{theme_label}`) RETURN n.name as RIName"
        for rule_info in rule_results.values():
            cypher_str = generate_cypher_path_query(theme_label, rule_info["chain"])
            candidate_rule = [{
                "rule_name": rule_info["rule_name"],
                "rule_desc": rule_info["rule_name"],
                "getIn4simi": get_in_4_simi,
                "rule_path": cypher_str,
            }]
            feasible_rule, _ = validate_rules_and_collect(
                candidate_rule, selected_main_scenario, scene, 2, theme_label
            )
            if not feasible_rule:
                continue
            item = feasible_rule[0]["final_rule"]
            rule_data = [
                selected_main_scenario,
                scene,
                item["rule_name"],
                item["rule_path"],
                item["getIn4simi"],
                item["rule_desc"],
                "",
                "",
            ]
            event_queue.put(sse_text("正在保存规则..."))
            insert_new_data(connection, rule_data, theme_label, scene, selected_main_scenario)
            insert_count += 1
        return insert_count
    finally:
        connection.close()


def run_file_rule_generation(file_bytes: bytes, selected_main_topic: str, selected_scenario: str, user_id: str, event_queue):
    # uploadRule 接口主流程：读取上传文本 -> 大模型清洗 -> 解析规则链 -> 校验并保存。
    total_start = now_ts()
    theme_label = resolve_theme_label(selected_main_topic, user_id)

    event_queue.put(sse_text("正在读取上传文件..."))
    try:
        rule_des = file_bytes.decode("utf-8")
    except Exception:
        event_queue.put(sse_json({"success": False, "error": "文件内容解析失败，请确保为 UTF-8 编码"}))
        return
    if not rule_des.strip():
        event_queue.put(sse_json({"success": False, "error": "上传文件内容为空"}))
        return

    event_queue.put(sse_text("正在清洗规则描述..."))
    response_content = qwen_api([{"role": "user", "content": build_file_rewrite_prompt(rule_des)}])
    rule_des = normalize_rule_description(response_content)

    event_queue.put(sse_text("正在解析规则链..."))
    rule_results = parse_rule_file_lines(rule_des, theme_label)
    if not rule_results:
        event_queue.put(sse_json({"success": False, "error": "未生成任何候选规则"}))
        return

    event_queue.put(sse_text("正在校验并保存规则..."))
    insert_count = save_file_rules(rule_results, selected_main_topic, selected_scenario, theme_label, event_queue)
    if insert_count == 0:
        event_queue.put(sse_json({"success": False, "error": "规则校验后无可保存结果"}))
        return

    event_queue.put(
        sse_json({
            "success": True,
            "message": "规则文件处理成功",
            "insert_count": insert_count,
            "total_cost": cost_str(total_start),
        })
    )


async def handle_rule_generation(payload: dict):
    q = queue.Queue()

    def worker():
        try:
            run_rule_generation(payload, q)
        except Exception as exc:
            q.put(sse_json({"success": False, "error": f"规则生成异常: {exc}"}))
        finally:
            q.put(None)

    threading.Thread(target=worker, daemon=True).start()
    return stream_from_queue(q)


async def handle_upload_rule(file: UploadFile, selected_main_topic: str, selected_scenario: str, user_id: str):
    file_bytes = await file.read()
    q = queue.Queue()

    def worker():
        try:
            run_file_rule_generation(file_bytes, selected_main_topic, selected_scenario, user_id, q)
        except Exception as exc:
            q.put(sse_json({"success": False, "error": f"规则文件处理异常: {exc}"}))
        finally:
            q.put(None)

    threading.Thread(target=worker, daemon=True).start()
    return stream_from_queue(q)
