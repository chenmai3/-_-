import re
from typing import Any, Dict, List, Optional

from vue_api.common.neo4j_client import (
    create_neo4j_driver,
    query_new_neo4j as run_neo4j_query,
)


def create_driver(kg: str = ""):
    # 公共函数：根据图谱类型创建 Neo4j driver。
    return create_neo4j_driver(kg)


def create_general_graph_driver():
    # rule_generation 内部函数：创建通用图谱 Neo4j driver。
    return create_driver("")


def query_new_neo4j(query, parameters=None, timeout=30, kg=""):
    # 文件规则解析内部函数：保留失败返回空列表的领域兼容行为。
    try:
        return run_neo4j_query(query, parameters=parameters, timeout=timeout, kg=kg)
    except Exception as exc:
        print(f"[rule_construct] Neo4j 查询失败: {exc}; query={query}")
        return []


def get_simple_paths(
        driver,
        label: str,
        scene: Optional[str] = None,
        max_hops: int = 10,
        limit: int = 50,
):
    # rule_generation 内部函数：读取用于模板挖掘的起点到终点简单路径。
    safe_label = str(label).replace("`", "")
    safe_scene = str(scene or "").replace("\\", "\\\\").replace("'", "\\'")
    cypher = f"""
    MATCH p = (s:`{safe_label}` {{scene: '{safe_scene}'}})-[*1..{max_hops}]->(t:`{safe_label}` {{scene: '{safe_scene}'}})
    WHERE
      NOT ()-[]->(s)
      AND NOT (t)-[]->()

    WITH p, [n IN nodes(p) | coalesce(n.name, "")] AS node_names,
            [r IN relationships(p) | type(r)] AS rel_types

    RETURN
      reduce(s = node_names[0], i IN range(0, size(rel_types)-1) |
             s + "-[" + rel_types[i] + "]->" + node_names[i+1]) AS path_str,
      length(p) AS hops
    ORDER BY hops DESC
    LIMIT {limit}
    """
    res = []
    try:
        with driver.session() as session:
            result = session.run(cypher)
            for record in result:
                res.append(record["path_str"])
    except Exception as exc:
        print(f"[rule_construct] 简单路径查询失败: {exc}; cypher={cypher}")
    return res


def parameterize_rule_query(rule_path: str) -> str:
    # uploadRule 内部函数：把规则路径中的实体占位符改为 Neo4j 参数。
    query = rule_path
    query = query.replace('"{entityname}"', "$entityname")
    query = query.replace("'{entityname}'", "$entityname")
    query = query.replace("{entityname}", "$entityname")
    return query


def neo4j_path_to_text(path_obj) -> str:
    try:
        nodes = list(path_obj.nodes)
        rels = list(path_obj.relationships)
        if not nodes:
            return ""

        names = [str(node.get("name", "")) for node in nodes]
        text = names[0]
        for index, rel in enumerate(rels):
            text += f"-[{rel.type}]->{names[index + 1]}"
        return text
    except Exception:
        return str(path_obj)


def extract_relation_chain_from_path_text(path_text: str) -> List[str]:
    if not path_text:
        return []
    return re.findall(r"-\[([^\]]+)\]->", path_text)


def choose_best_subpath(path_items: List[Dict[str, Any]]) -> Optional[Dict[str, Any]]:
    # uploadRule 内部函数：优先选择最长、关系覆盖最多的可行路径。
    if not path_items:
        return None

    def score(item):
        path_text = item.get("path_text", "")
        rels = extract_relation_chain_from_path_text(path_text)
        return len(rels), len(set(rels)), len(path_text)

    return max(path_items, key=score)


def build_driver_and_label(selectedMainScenario: str, custom_label: Optional[str] = None):
    # uploadRule 内部函数：按主题选择验证规则使用的 Neo4j driver 和 label。
    if selectedMainScenario == "轨交诊断":
        return create_driver("kdzn"), "kedazhineng"
    if selectedMainScenario == "家谱问答":
        return create_driver("jiapu"), "jiapuwenda"
    return create_driver(""), custom_label if custom_label else "your_custom_label"


def fetch_entry_candidates(driver, get_in_query: str, limit: int = 20) -> List[str]:
    # uploadRule 内部函数：执行 getIn4simi，提取入口候选实体。
    if not get_in_query:
        return []

    query = get_in_query.strip()
    if " limit " not in query.lower():
        query += f" LIMIT {limit}"

    names = []
    seen = set()
    try:
        with driver.session() as session:
            result = session.run(query)
            for record in result:
                val = None
                if "RIName" in record.keys():
                    val = record["RIName"]
                elif len(record.keys()) == 1:
                    val = record[0]

                if val is None:
                    continue

                val = str(val).strip()
                if val and val not in seen:
                    seen.add(val)
                    names.append(val)
    except Exception as exc:
        print(f"[rule_construct] 入口候选查询失败: {exc}; query={query}")
    return names


def run_rule_on_entries(
        driver,
        rule_path: str,
        entry_names: List[str],
        per_entry_limit: int = 5,
) -> List[Dict[str, Any]]:
    # uploadRule 内部函数：对候选入口实体执行 rule_path 并收集可行路径。
    if not rule_path or not entry_names:
        return []

    query = parameterize_rule_query(rule_path)
    if " limit " not in query.lower():
        query += f" LIMIT {per_entry_limit}"

    matched = []
    with driver.session() as session:
        for entry_name in entry_names:
            try:
                result = session.run(query, entityname=entry_name)
                for record in result:
                    path_obj = None
                    if "p" in record.keys():
                        path_obj = record["p"]
                    elif len(record.keys()) == 1:
                        path_obj = record[0]

                    if path_obj is None:
                        continue

                    matched.append({
                        "entry_name": entry_name,
                        "path_text": neo4j_path_to_text(path_obj),
                    })
            except Exception:
                continue

    return [item for item in matched if item.get("path_text")]
