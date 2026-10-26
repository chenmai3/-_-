import json
import re
from typing import Any, Dict


def parse_file_rule_response(response_content):
    # uploadRule 内部函数：解析 LLM 输出的规则名、关系链、入口实体。
    if not response_content:
        return "", [], ""
    try:
        result_json = parse_llm_json(response_content)
        if not isinstance(result_json, dict):
            return "", [], ""
        rule_name = str(result_json.get("rule_name", "") or "")
        chain = result_json.get("relation_chain", [])
        if not isinstance(chain, list):
            chain = []
        chain = [str(item) for item in chain if str(item).strip()]
        rule_entry = str(result_json.get("rule_entry", "") or "")
        return rule_name, chain, rule_entry
    except Exception as exc:
        print(f"[rule_construct] 文件规则解析 JSON 失败: {exc}")
        return "", [], ""


def generate_cypher_path_query(koqatheme_label_with_ID, relation_chain, entity_name="entityname"):
    # uploadRule 内部函数：根据关系链生成固定入口占位的路径查询 Cypher。
    if not relation_chain:
        raise ValueError("关系链不能为空")

    path_pattern = "".join([
        f"-[:`{str(rel).replace('`', '')}`]->(x{index})"
        for index, rel in enumerate(relation_chain)
    ])
    start_node = f"(n:`{str(koqatheme_label_with_ID).replace('`', '')}` {{name: \"{{{entity_name}}}\"}})"
    return f"MATCH p = {start_node}{path_pattern} RETURN p"


def normalize_candidate_rule(item: Dict[str, Any]) -> Dict[str, str]:
    # uploadRule 内部函数：统一候选规则字段名。
    return {
        "rule_name": item.get("rule_name", "") or "",
        "rule_desc": item.get("rule_desc", "") or item.get("user_rule_desc", "") or "",
        "rule_path": item.get("rule_path") or item.get("rule_path_list") or "",
        "getIn4simi": item.get("getIn4simi") or item.get("get_in_4_simi") or "",
    }


def extract_json_text(text: str) -> str:
    if not text:
        return text
    text = text.strip()
    if text.startswith("```"):
        match = re.search(r"```(?:json)?\s*([\s\S]*?)\s*```", text)
        if match:
            return match.group(1).strip()
    return text


def parse_llm_json(text: str):
    # 公共函数：兼容纯 JSON、markdown fenced JSON、前后带解释文本的模型输出。
    raw = extract_json_text(text)
    try:
        return json.loads(raw)
    except json.JSONDecodeError:
        arr_match = re.search(r"(\[[\s\S]*\])", raw)
        if arr_match:
            return json.loads(arr_match.group(1))
        obj_match = re.search(r"(\{[\s\S]*\})", raw)
        if obj_match:
            return json.loads(obj_match.group(1))
        raise
