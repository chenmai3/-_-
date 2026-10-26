import json
import re
from collections import defaultdict
from concurrent.futures import ThreadPoolExecutor, as_completed

from .prompts import build_rule_name_prompt


def split_into_batches(items, batch_num=2):
    n = len(items)
    if n == 0:
        return []
    batch_size = (n + batch_num - 1) // batch_num
    return [items[i:i + batch_size] for i in range(0, n, batch_size)]


def dedupe_templates(templates):
    # rule_generation 内部函数：按入口角色、关系链、出口角色去重。
    seen = set()
    out = []
    for template in templates:
        key = (
            tuple(template["entry_sig"]),
            tuple(template["rel_chain"]),
            tuple(template["exit_sig"]),
        )
        if key in seen:
            continue
        seen.add(key)
        out.append(template)
    return out


def build_getin_query(label, scene, entry_sig):
    # rule_generation 内部函数：根据入口节点角色自动生成召回入口查询。
    label_expr = f"`{label}`"
    scene = scene.replace("'", "\\'")
    prev_rel, next_rel = entry_sig

    if prev_rel == "__START__" and next_rel == "__END__":
        return f"MATCH (ri:{label_expr} {{scene:'{scene}'}}) RETURN DISTINCT ri.name AS RIName"

    if prev_rel == "__START__":
        return (
            f"MATCH (ri:{label_expr} {{scene:'{scene}'}})-[:`{next_rel}`]->() "
            f"WHERE NOT ()-[]->(ri) RETURN DISTINCT ri.name AS RIName"
        )

    if next_rel == "__END__":
        return (
            f"MATCH ()-[:`{prev_rel}`]->(ri:{label_expr} {{scene:'{scene}'}}) "
            f"WHERE NOT (ri)-[]->() RETURN DISTINCT ri.name AS RIName"
        )

    return (
        f"MATCH ()-[:`{prev_rel}`]->(ri:{label_expr} {{scene:'{scene}'}})-[:`{next_rel}`]->() "
        f"RETURN DISTINCT ri.name AS RIName"
    )


def build_rule_path(label, scene, rel_chain):
    # rule_generation 内部函数：根据关系链自动生成 rule_path。
    label_expr = f"`{label}`"
    scene = scene.replace("'", "\\'")
    chain = "".join([f"-[:`{rel}`]->()" for rel in rel_chain])
    return f'MATCH p=(n:{label_expr} {{name: "{{entityname}}", scene:\'{scene}\'}}){chain} RETURN p'


def parse_json_array_from_llm(ans: str):
    if not ans:
        return []
    if ans.startswith("```"):
        match = re.search(r"```(?:json)?\s*(\[[\s\S]*?\])\s*```", ans)
        if match:
            return json.loads(match.group(1))
        return json.loads(ans.strip("` \n"))
    parsed = json.loads(ans)
    return parsed if isinstance(parsed, list) else []


class RuleTemplateMiner:
    # rule_generation 内部类：从图谱简单路径中枚举和聚合可复用规则模板。
    def __init__(self, min_support=2, max_hops=3):
        self.min_support = min_support
        self.max_hops = max_hops

    def parse_path(self, path_text: str):
        nodes, rels = [path_text.split("-[", 1)[0].strip()], []
        for part in path_text.split("-[")[1:]:
            rel, rest = part.split("]->", 1)
            rels.append(rel.strip().replace("`", "").replace("'", ""))
            nodes.append(rest.split("-[", 1)[0].strip())
        return nodes, rels

    def node_signature(self, rels, node_idx):
        prev_rel = rels[node_idx - 1] if node_idx > 0 else "__START__"
        next_rel = rels[node_idx] if node_idx < len(rels) else "__END__"
        return prev_rel, next_rel

    def enumerate_templates(self, path_text: str):
        nodes, rels = self.parse_path(path_text)
        out = []
        for start_idx in range(len(nodes) - 1):
            max_end = min(len(nodes) - 1, start_idx + self.max_hops)
            for end_idx in range(start_idx + 1, max_end + 1):
                rel_chain = tuple(rels[start_idx:end_idx])
                entry_sig = self.node_signature(rels, start_idx)
                exit_sig = self.node_signature(rels, end_idx)
                out.append({
                    "template_key": (entry_sig, rel_chain, exit_sig),
                    "entry_sig": entry_sig,
                    "exit_sig": exit_sig,
                    "rel_chain": list(rel_chain),
                    "entry_example": nodes[start_idx],
                    "exit_example": nodes[end_idx],
                    "sample_path": path_text,
                })
        return out

    def mine_templates(self, path_list):
        groups = defaultdict(lambda: {
            "support": 0,
            "entry_examples": set(),
            "exit_examples": set(),
            "sample_paths": [],
        })
        for path_text in path_list:
            seen_in_one_path = set()
            for item in self.enumerate_templates(path_text):
                key = item["template_key"]
                if key in seen_in_one_path:
                    continue
                seen_in_one_path.add(key)
                group = groups[key]
                group["support"] += 1
                group["entry_examples"].add(item["entry_example"])
                group["exit_examples"].add(item["exit_example"])
                if len(group["sample_paths"]) < 3:
                    group["sample_paths"].append(item["sample_path"])

        results = []
        for (entry_sig, rel_chain, exit_sig), group in groups.items():
            if group["support"] < self.min_support:
                continue
            results.append({
                "entry_sig": entry_sig,
                "exit_sig": exit_sig,
                "rel_chain": list(rel_chain),
                "support": group["support"],
                "entry_examples": list(group["entry_examples"])[:5],
                "exit_examples": list(group["exit_examples"])[:5],
                "sample_paths": group["sample_paths"],
            })
        results.sort(key=lambda item: (-item["support"], -len(item["rel_chain"])))
        return results


def build_candidate_rules(templates, label, scene):
    # rule_generation 内部函数：把模板转换成规则候选。
    candidate_rules = []
    for template in templates:
        candidate_rules.append({
            "entry_sig": template["entry_sig"],
            "exit_sig": template["exit_sig"],
            "rel_chain": template["rel_chain"],
            "support": template["support"],
            "entry_examples": template["entry_examples"],
            "exit_examples": template["exit_examples"],
            "sample_paths": template["sample_paths"],
            "getIn4simi": build_getin_query(label, scene, template["entry_sig"]),
            "rule_path": build_rule_path(label, scene, template["rel_chain"]),
        })
    return candidate_rules


def build_rule_name_input(candidate_rules):
    # rule_generation 内部函数：裁剪 LLM 命名只需要的字段。
    return [{
        "entry_sig": rule["entry_sig"],
        "exit_sig": rule["exit_sig"],
        "rel_chain": rule["rel_chain"],
        "support": rule["support"],
        "entry_examples": rule["entry_examples"],
        "exit_examples": rule["exit_examples"],
        "sample_paths": rule["sample_paths"],
        "getIn4simi": rule["getIn4simi"],
        "rule_path": rule["rule_path"],
    } for rule in candidate_rules]


def call_qwen_for_batch(batch, qwen_func):
    # rule_generation 内部函数：调用 LLM 为一批模板生成规则名。
    try:
        ans = qwen_func([{"role": "user", "content": build_rule_name_prompt(batch)}])
        return parse_json_array_from_llm(ans)
    except Exception as exc:
        print(f"[rule_construct] 规则命名结果解析失败: {exc}")
        return []


def name_rules_with_llm(llm_input, qwen_func, batch_num=2):
    # rule_generation 内部函数：并行调用 LLM 命名规则模板。
    result = []
    batches = split_into_batches(llm_input, batch_num=batch_num)
    with ThreadPoolExecutor(max_workers=batch_num) as executor:
        futures = [executor.submit(call_qwen_for_batch, batch, qwen_func) for batch in batches]
        for future in as_completed(futures):
            try:
                result.extend(future.result())
            except Exception as exc:
                print(f"[rule_construct] 规则命名批次失败: {exc}")
    return result


def generate_rule_names_from_paths(path_list, scene, label, qwen_func):
    # rule_generation 对外函数：从简单路径挖掘模板并生成最终规则名列表。
    miner = RuleTemplateMiner(min_support=2, max_hops=3)
    templates = dedupe_templates(miner.mine_templates(path_list))
    candidate_rules = build_candidate_rules(templates, label, scene)
    return name_rules_with_llm(build_rule_name_input(candidate_rules), qwen_func, batch_num=2)
