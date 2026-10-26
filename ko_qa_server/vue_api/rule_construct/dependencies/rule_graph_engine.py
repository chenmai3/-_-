import time
from typing import Any, Dict, List, Optional, Tuple

from .graph_queries import (
    build_driver_and_label,
    choose_best_subpath,
    create_general_graph_driver,
    fetch_entry_candidates,
    get_simple_paths,
    query_new_neo4j,
    run_rule_on_entries,
)
from .llm_clients import call_qwen_max, call_qwen_small
from .prompts import (
    build_file_rule_parse_prompt,
    build_repair_rule_prompt,
    build_semantic_validate_prompt,
)
from .rule_utils import (
    generate_cypher_path_query as generate_cypher_path_query,
    normalize_candidate_rule,
    parse_file_rule_response,
    parse_llm_json,
)
from .template_mining import generate_rule_names_from_paths


def now_ts():
    return time.perf_counter()


def cost_str(start):
    return f"{time.perf_counter() - start:.3f}s"


def read_simple_paths_for_rule_generation(q, scene, label):
    # rule_generation 内部函数：从图谱中读取用于模板挖掘的简单路径。
    step_start = now_ts()
    driver = create_general_graph_driver()
    print(f"[计时] Neo4j driver 初始化耗时: {cost_str(step_start)}")
    try:
        time.sleep(0.1)
        q.put("data: 正在图谱中检索简单路径...\n\n")
        step_start = now_ts()
        paths = get_simple_paths(
            driver=driver,
            label=label,
            scene=scene,
            limit=50,
        )
        print(f"[计时] get_simple_paths 耗时: {cost_str(step_start)}，路径数: {len(paths)}")
        return paths
    finally:
        close_start = now_ts()
        driver.close()
        print(f"[计时] Neo4j driver 关闭耗时: {cost_str(close_start)}")


def generate_rule_names(q, paths, scene, label):
    # rule_generation 内部函数：从简单路径归纳模板并调用 LLM 命名。
    q.put("data: 正在根据路径结构归纳规则模板...\n\n")
    step_start = now_ts()
    result = generate_rule_names_from_paths(
        path_list=paths,
        scene=scene,
        label=label,
        qwen_func=call_qwen_small,
    )
    print(f"[计时] generate_rule_names_from_paths 耗时: {cost_str(step_start)}")
    return result


def read_graph_from_neo4j(q, scene, koqatheme_label_with_ID):
    total_start = now_ts()
    paths = read_simple_paths_for_rule_generation(q, scene, koqatheme_label_with_ID)
    if not paths:
        return False, []

    final_result = generate_rule_names(q, paths, scene, koqatheme_label_with_ID)
    print(f"[计时] read_graph_from_neo4j 总耗时: {cost_str(total_start)}")

    return True, final_result
















def get_relation_list(match_str):
    # uploadRule 内部函数：查询当前图谱已有关系集合，供 LLM 约束输出。
    relation_result = query_new_neo4j(match_str)
    relation_list = []
    for r in relation_result:
        try:
            relation_list.append(r["relationshipType"])
        except Exception:
            continue
    return relation_list




def file_rule_parse(match_str, rule_des):
    # uploadRule 接口内部函数：将上传文件中的单条自然语言规则解析成规则链。
    relation_list = get_relation_list(match_str)
    prompt = build_file_rule_parse_prompt(relation_list, rule_des)
    response_content = call_qwen_max([{"role": "user", "content": prompt}])
    return parse_file_rule_response(response_content)
























def default_semantic_result(rule_item: Dict[str, str], reason="语义验证结果解析失败") -> Dict[str, Any]:
    # uploadRule 内部函数：语义校验失败时保持流程不断开。
    return {
        "passed": False,
        "reason": reason,
        "problem_type": "other",
        "suggestion": "请检查 LLM 输出格式",
        "normalized_rule_name": rule_item.get("rule_name", ""),
        "normalized_rule_desc": rule_item.get("rule_desc", ""),
    }


def normalize_semantic_result(data: Dict[str, Any], rule_item: Dict[str, str]) -> Dict[str, Any]:
    # uploadRule 内部函数：把 LLM 语义校验 JSON 归一成稳定结构。
    return {
        "passed": bool(data.get("passed", False)),
        "reason": data.get("reason", ""),
        "problem_type": data.get("problem_type", "other"),
        "suggestion": data.get("suggestion", ""),
        "normalized_rule_name": data.get("normalized_rule_name", rule_item.get("rule_name", "")),
        "normalized_rule_desc": data.get("normalized_rule_desc", rule_item.get("rule_desc", "")),
    }


def llm_semantic_validate(
        rule_item: Dict[str, str],
        best_path: str
) -> Dict[str, Any]:
    # uploadRule 内部函数：让 LLM 判断候选规则和图谱路径语义是否一致。
    prompt = build_semantic_validate_prompt(rule_item, best_path)
    messages = [{"role": "user", "content": prompt}]
    ans = call_qwen_small(messages)

    try:
        data = parse_llm_json(ans)
        if isinstance(data, dict):
            return normalize_semantic_result(data, rule_item)
    except Exception as exc:
        print(f"[rule_construct] 语义校验结果解析失败: {exc}")

    return default_semantic_result(rule_item)


def llm_repair_rule(
        rule_item: Dict[str, str],
        best_path: str
) -> Optional[Dict[str, str]]:
    prompt = build_repair_rule_prompt(rule_item, best_path)
    messages = [{"role": "user", "content": prompt}]
    ans = call_qwen_small(messages)

    try:
        data = parse_llm_json(ans)
        if isinstance(data, dict) and data.get("getIn4simi") and data.get("rule_path"):
            return {
                "rule_name": data.get("rule_name", rule_item.get("rule_name", "")),
                "rule_desc": data.get("rule_desc", rule_item.get("rule_desc", "")),
                "getIn4simi": data["getIn4simi"],
                "rule_path": data["rule_path"]
            }
    except Exception:
        return None

    return None


def rule_validation_result(
        status: str,
        original_rule: Dict[str, Any],
        final_rule: Dict[str, Any],
        entry_candidates=None,
        best_path: str = "",
        semantic_validation=None,
        repair_rounds: int = 0,
        reason: str = "",
) -> Dict[str, Any]:
    # uploadRule 内部函数：统一单条规则校验的返回结构。
    result = {
        "status": status,
        "original_rule": original_rule,
        "final_rule": final_rule,
        "entry_candidates": (entry_candidates or [])[:10],
        "best_path": best_path,
    }
    if semantic_validation is not None:
        result["semantic_validation"] = semantic_validation
    if repair_rounds:
        result["repair_rounds"] = repair_rounds
    if reason:
        result["reason"] = reason
    return result


def fetch_rule_matches(driver, current_rule: Dict[str, str]):
    # uploadRule 内部函数：根据 getIn4simi 找入口实体，再执行 rule_path 找真实路径。
    entry_candidates = fetch_entry_candidates(driver, current_rule["getIn4simi"], limit=20)
    matched_items = run_rule_on_entries(
        driver=driver,
        rule_path=current_rule["rule_path"],
        entry_names=entry_candidates,
        per_entry_limit=5,
    )
    return entry_candidates, matched_items


def apply_semantic_result(current_rule: Dict[str, str], semantic_result: Dict[str, Any]):
    # uploadRule 内部函数：把语义校验归一后的规则名/描述写回当前规则。
    current_rule["rule_name"] = semantic_result.get("normalized_rule_name", current_rule["rule_name"])
    current_rule["rule_desc"] = semantic_result.get("normalized_rule_desc", current_rule["rule_desc"])


def max_rounds_failed_result(original_rule, current_rule, entry_candidates, best_path, semantic_result, round_idx):
    # uploadRule 内部函数：语义校验达到最大轮次后的失败结果。
    return rule_validation_result(
        "failed",
        original_rule,
        current_rule,
        entry_candidates,
        best_path,
        semantic_result,
        round_idx,
        "达到最大迭代次数后仍未通过语义验证",
    )


def repair_failed_result(original_rule, current_rule, entry_candidates, best_path, semantic_result, round_idx):
    # uploadRule 内部函数：LLM 修复失败后的结果。
    return rule_validation_result(
        "failed",
        original_rule,
        current_rule,
        entry_candidates,
        best_path,
        semantic_result,
        round_idx,
        "LLM 路径修复失败",
    )


def try_repair_rule(current_rule, best_path):
    # uploadRule 内部函数：尝试用 LLM 修复语义未通过的规则。
    return llm_repair_rule(current_rule, best_path)


def semantic_validate_and_repair_loop(
        original_rule: Dict[str, Any],
        current_rule: Dict[str, Any],
        entry_candidates,
        best_path: str,
        max_llm_rounds: int,
) -> Dict[str, Any]:
    # uploadRule 内部函数：执行语义校验，必要时调用 LLM 修复规则。
    last_semantic_result = None
    for round_idx in range(max_llm_rounds + 1):
        semantic_result = llm_semantic_validate(current_rule, best_path)
        last_semantic_result = semantic_result
        apply_semantic_result(current_rule, semantic_result)

        if semantic_result.get("passed", False):
            return rule_validation_result(
                "passed", original_rule, current_rule, entry_candidates, best_path, semantic_result, round_idx
            )

        if round_idx >= max_llm_rounds:
            return max_rounds_failed_result(
                original_rule, current_rule, entry_candidates, best_path, semantic_result, round_idx
            )

        repaired_rule = try_repair_rule(current_rule, best_path)
        if not repaired_rule:
            return repair_failed_result(
                original_rule, current_rule, entry_candidates, best_path, last_semantic_result, round_idx
            )
        current_rule = repaired_rule

    return rule_validation_result(
        "failed",
        original_rule,
        current_rule,
        entry_candidates,
        best_path,
        last_semantic_result,
        max_llm_rounds,
        "未知失败",
    )


def validate_single_rule_v2(
        driver,
        rule_item: Dict[str, Any],
        max_llm_rounds: int = 2
) -> Dict[str, Any]:
    original_rule = normalize_candidate_rule(rule_item)
    current_rule = dict(original_rule)

    try:
        entry_candidates, matched_items = fetch_rule_matches(driver, current_rule)
    except Exception as exc:
        return rule_validation_result(
            "discarded", original_rule, current_rule, reason=f"图谱路径检索异常: {exc}"
        )

    if not matched_items:
        return rule_validation_result(
            "discarded", original_rule, current_rule, entry_candidates, reason="图谱中不存在任意可行子路径"
        )

    best_item = choose_best_subpath(matched_items)
    best_path = best_item["path_text"] if best_item else ""
    return semantic_validate_and_repair_loop(
        original_rule, current_rule, entry_candidates, best_path, max_llm_rounds
    )


def validate_rules_and_collect(
        candidate_rules: List[Dict[str, Any]],
        selectedMainScenario: str,
        scene: str,
        max_llm_rounds: int = 2,
        custom_label: Optional[str] = None
) -> Tuple[List[Dict[str, Any]], List[Dict[str, Any]]]:
    driver, koqatheme_label_with_ID = build_driver_and_label(
        selectedMainScenario=selectedMainScenario,
        custom_label=custom_label
    )

    feasible_rules = []
    discarded_rules = []

    try:
        for idx, rule_item in enumerate(candidate_rules, start=1):
            try:
                result = validate_single_rule_v2(
                    driver=driver,
                    rule_item=rule_item,
                    max_llm_rounds=max_llm_rounds
                )
            except Exception as exc:
                result = {
                    "status": "failed",
                    "original_rule": normalize_candidate_rule(rule_item),
                    "final_rule": normalize_candidate_rule(rule_item),
                    "entry_candidates": [],
                    "best_path": "",
                    "reason": f"第 {idx} 条规则验证异常: {exc}",
                }

            if result["status"] == "passed":
                feasible_rules.append(result)
            else:
                discarded_rules.append(result)

        return feasible_rules, discarded_rules

    finally:
        driver.close()
