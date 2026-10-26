import difflib
import re
import string

from ..common.neo4j_client import query_new_neo4j


def neo4j_kg(selectedMainScenario: str) -> str:
    # 公共函数：根据主题选择 Neo4j 数据源。
    if selectedMainScenario in ("家谱问答", "家谱主题问答"):
        return "jiapu"
    if selectedMainScenario in ("轨交诊断", "kdzn_test"):
        return "kdzn"
    return ""


def run_neo4j_query(query_text: str, selectedMainScenario: str):
    # 公共函数：集中执行 Neo4j 查询，异常时返回空列表，避免接口直接中断。
    if not query_text:
        return []
    try:
        return query_new_neo4j(query_text, kg=neo4j_kg(selectedMainScenario)) or []
    except Exception as exc:
        print(f"[rule_construct] Neo4j 查询失败: {exc}; query={query_text}")
        return []


def relation_type(rel, selectedMainScenario: str) -> str:
    # 公共函数：兼容普通图谱关系类型和家谱图谱 name 属性关系。
    if selectedMainScenario == "家谱问答":
        rel_name = rel.get("name") if hasattr(rel, "get") else None
        rel_type_raw = str(rel_name) if rel_name is not None else getattr(rel, "type", str(type(rel)))
    else:
        rel_type_raw = str(type(rel))
    match = re.search(r"'([^']+)'\>", rel_type_raw)
    return match.group(1).split(".")[-1] if match else rel_type_raw


def path_from_record(record, selectedMainScenario: str):
    # 公共函数：兼容 record["p"] 和 record[0] 两种老返回结构。
    try:
        if selectedMainScenario == "轨交诊断" and isinstance(record, dict):
            return record.get("p")
        if isinstance(record, dict):
            return record.get("p") or next(iter(record.values()))
        return record[0]
    except Exception:
        return None


def node_name(node) -> str:
    try:
        return str(node["name"])
    except Exception:
        return ""


def format_neo4j_paths(records, selectedMainScenario: str):
    # 公共函数：把 Neo4j path 结果转成前端渲染所需的路径字符串和分层三元组。
    formatted_paths = []
    path_entities = []

    for record in records or []:
        path = path_from_record(record, selectedMainScenario)
        if not path:
            continue
        nodes = list(getattr(path, "nodes", []) or [])
        relationships = list(getattr(path, "relationships", []) or [])
        if not nodes:
            continue

        path_str = node_name(nodes[0])
        triplets_with_level = []
        for index, rel in enumerate(relationships):
            if index + 1 >= len(nodes):
                break
            rel_type = relation_type(rel, selectedMainScenario)
            if rel_type == "kedazhineng":
                continue

            left_node = nodes[index]
            right_node = nodes[index + 1]
            start_node = getattr(rel, "start_node", None)
            end_node = getattr(rel, "end_node", None)
            if start_node == left_node and end_node == right_node:
                source, target = left_node, right_node
                tokens = ("-", "->")
            elif start_node == right_node and end_node == left_node:
                source, target = right_node, left_node
                tokens = ("<-", "-")
            else:
                source, target = start_node or left_node, end_node or right_node
                tokens = ("-", "->")

            path_str += f"{tokens[0]}{rel_type}{tokens[1]}{node_name(target)}"
            triplets_with_level.append({
                "source": {"name": node_name(source), "level": index if source == left_node else index + 1},
                "relation": {"type": rel_type},
                "target": {"name": node_name(target), "level": index if target == left_node else index + 1},
            })

        if triplets_with_level:
            formatted_paths.append(path_str)
            path_entities.append(triplets_with_level)
    return formatted_paths, path_entities


def split_rule_path(path: str):
    # 公共函数：把 "A-rel->B-rel->C" 拆成节点和关系。
    parts = str(path or "").strip(".").split("->")
    nodes = []
    relationships = []
    for index, part in enumerate(parts):
        if index < len(parts) - 1:
            node, rel = part.rsplit("-", 1)
            nodes.append(node.strip())
            relationships.append(rel.strip())
        else:
            nodes.append(part.strip())
    return nodes, relationships


def extract_entities_from_path(path_str):
    # rule_generate 接口内部函数：从格式化路径字符串中抽取实体名。
    parts = re.split(r'(?:-[^-<>]+->|<-[^-<>]+-)', path_str)
    return [part for part in parts if part]


def best_matching_path(paths: list, entity: str, similarity_threshold: float = 0.8):
    # 公共函数：从路径列表中找和目标实体最相近的节点。
    best = {"nodes": [], "relationships": [], "entity_index": -1, "similarity": 0}
    cleaned_entity = str(entity or "").strip(string.punctuation + " ")
    for path in paths or []:
        try:
            nodes, relationships = split_rule_path(path)
        except ValueError:
            continue
        for index, node in enumerate(nodes):
            cleaned_node = node.strip(string.punctuation + " ")
            similarity = difflib.SequenceMatcher(None, cleaned_node, cleaned_entity).ratio()
            if similarity > best["similarity"]:
                best = {
                    "nodes": nodes,
                    "relationships": relationships,
                    "entity_index": index,
                    "similarity": similarity,
                }
    if best["similarity"] < similarity_threshold:
        return None
    return best


def generate_cypher_query(selectedMainScenario, selectedMainScenario_label_with_ID, paths: list, entity: str, scene,
                          similarity_threshold: float = 0.8) -> str:
    # rule_generate 接口内部函数：根据入口实体所在路径生成规则入口查询。
    if not paths:
        return "错误: 路径列表为空"

    if selectedMainScenario == '家谱问答':
        selectedMainScenario_label_with_ID = 'huaputong'
    matched = best_matching_path(paths, entity, similarity_threshold)
    if not matched:
        return ''

    sub_relationships = matched["relationships"][:matched["entity_index"]]
    query_parts = []
    return_parts = []
    query_parts.append(f'(f:{selectedMainScenario_label_with_ID})')

    for i in range(len(sub_relationships)):
        node_name = 'R' + str(i + 1) if i < len(sub_relationships) - 1 else 'RI'
        query_parts.append(f'-[:{sub_relationships[i]}]->({node_name})')
        return_parts.append(f'{node_name}.name AS {node_name}Name')

    match_clause = 'MATCH ' + ''.join(query_parts)
    last_var = 'RI' if sub_relationships else 'f'
    return_clause = 'RETURN ' + ', '.join(return_parts) if return_parts else f'RETURN {last_var}.name AS RIName'
    cypher_query = f"{match_clause}\n{return_clause}"
    if selectedMainScenario != '家谱问答':
        m = re.search(r'\bRETURN\b', cypher_query, flags=re.IGNORECASE)
        if not m:
            raise ValueError("查询语句中未找到 RETURN，无法自动插入场景条件。")
        before = cypher_query[:m.start()]
        after = cypher_query[m.start():]
        cypher_query = before.rstrip() + f"""\nWHERE {last_var}.scene = "{scene}"\n""" + after

    return cypher_query


def _inject_scene_filter_ri(query: str, scene: str) -> str:
    """
    仅针对变量 RI 注入 scene 过滤：
    - 如果已出现 RI.scene，则不注入；
    - 如果查询里没有变量 RI（精确匹配变量名），不注入；
    - 仅在存在 RETURN 子句时进行注入；
    """
    if not query or not scene:
        return query

    m = re.search(r'\bRETURN\b', query, flags=re.IGNORECASE)
    if not m:
        return query

    # 检查查询里是否真的存在变量 RI（避免把 RIName 之类误判）
    # 负/正向边界确保精确匹配独立标识符 RI
    if not re.search(r'(?<![A-Za-z0-9_])RI(?![A-Za-z0-9_])', query):
        # 没有 RI 变量，直接返回原查询，避免 "Variable `RI` not defined"
        return query

    before, after = query[:m.start()].rstrip(), query[m.start():]

    # 在 WHERE 里追加 / 新建 WHERE
    if re.search(r'\bWHERE\b', before, flags=re.IGNORECASE):
        return f'{before} AND RI.scene = "{scene}" {after}'
    else:
        return f'{before} WHERE RI.scene = "{scene}" {after}'


def query_2(selectedMainScenario, query, scene):
    # neo4j_match_1 接口内部函数：先执行规则入口查询，取 RIName 候选实体。
    scene = (scene or "").strip()
    query_text = query if selectedMainScenario == '轨交诊断' else _inject_scene_filter_ri(query, scene)
    return run_neo4j_query(query_text, selectedMainScenario)


def query_1(selectedMainScenario, query, scene):
    # neo4j_match / neo4j_match_1 接口内部函数：执行规则主体查询并格式化为前端图谱数据。
    result = run_neo4j_query(query, selectedMainScenario)
    return format_neo4j_paths(result, selectedMainScenario)


def query_rule(selectedMainScenario_label_with_ID, selectedMainScenario, scene, input_entity=''):
    # rule_generate 接口内部函数：查询入口实体可达的候选路径。
    if selectedMainScenario == "轨交诊断":
        query_ = f"""MATCH p=(f:kedazhineng {{name: "{scene}"}})-[*]->() 
        WHERE ANY(n IN nodes(p) WHERE n.name = "{input_entity}")
        RETURN p"""
    elif selectedMainScenario == "kdzn_test":
        query_ = f"""MATCH p=(f:kdzn)-[*]->() RETURN p"""
    elif selectedMainScenario == "家谱问答":
        query_ = f"""MATCH p=(f:huaputong {{name: "{input_entity}"}})-[*]->() RETURN p LIMIT 30"""
    else:
        query_ = f"""
        MATCH (f:{selectedMainScenario_label_with_ID} {{name: "{input_entity}"}})
        MATCH p = ()-[*]->(f)
        WHERE ALL(n IN nodes(p) WHERE n.scene = "{scene}")
        RETURN p
        ORDER BY length(p) DESC
        LIMIT 1
        """
    return format_neo4j_paths(run_neo4j_query(query_, selectedMainScenario), selectedMainScenario)


def query(selectedMainScenario_label_with_ID, selectedMainScenario, scene, input_entity=''):
    # rule_generate 接口内部函数：查询入口实体附近可用于匹配出口实体的候选路径。
    if selectedMainScenario == "轨交诊断":
        query_ = f"""MATCH p=(f:kedazhineng {{name: "{scene}"}})-[*]->() 
        WHERE ANY(n IN nodes(p) WHERE n.name = "{input_entity}")
        RETURN p"""
        result = run_neo4j_query(query_, selectedMainScenario)
    elif selectedMainScenario == "kdzn_test":
        query_ = f"""MATCH p=(f:kdzn)-[*]->() RETURN p"""
        result = run_neo4j_query(query_, selectedMainScenario)
    elif selectedMainScenario == "家谱问答":
        query_ = f"""
        MATCH (f:huaputong {{name: "{input_entity}"}})
        WHERE coalesce(f.scene, "曾国藩家谱") = "{scene}"
        MATCH p = (f)<-[*]->()
        RETURN p
        LIMIT 30
        """
        result = run_neo4j_query(query_, selectedMainScenario)
    elif selectedMainScenario == "家谱主题问答":
        query_out = f"""
        MATCH p=(f:{selectedMainScenario_label_with_ID} {{name: "{input_entity}"}})-[*]->()
        WHERE ALL(n IN nodes(p) WHERE n.scene = "{scene}")
        RETURN p 
        LIMIT 30
        """
        result = run_neo4j_query(query_out, selectedMainScenario)
        if not result:
            query_in = f"""
            MATCH p=(f:{selectedMainScenario_label_with_ID} {{name: "{input_entity}"}})<-[*]->()
            WHERE ALL(n IN nodes(p) WHERE n.scene = "{scene}")
            RETURN p 
            LIMIT 30
            """
            result = run_neo4j_query(query_in, selectedMainScenario)
    else:
        query_out = f"""
        MATCH p=(f:{selectedMainScenario_label_with_ID} {{name: "{input_entity}"}})-[*]->()
        WHERE ALL(n IN nodes(p) WHERE n.scene = "{scene}")
        RETURN p 
        LIMIT 30
        """
        result = run_neo4j_query(query_out, selectedMainScenario)
        if not result:
            query_in = f"""
            MATCH p=(f:{selectedMainScenario_label_with_ID} {{name: "{input_entity}"}})<-[*]->()
            WHERE ALL(n IN nodes(p) WHERE n.scene = "{scene}")
            RETURN p 
            LIMIT 30
            """
            result = run_neo4j_query(query_in, selectedMainScenario)
    return format_neo4j_paths(result, selectedMainScenario)


def generate_rule_path_cypher(selectedMainScenario, selectedMainScenario_label_with_ID, paths: list, output_entity: str,
                              similarity_threshold: float = 0.8) -> str:
    # rule_generate 接口内部函数：根据出口实体所在路径生成规则主体查询。
    if selectedMainScenario == '家谱问答':
        selectedMainScenario_label_with_ID = 'huaputong'
    matched = best_matching_path(paths, output_entity, similarity_threshold)
    if not matched:
        return ''

    def _qrel(s: str) -> str:
        return f'`{str(s).replace("`", "")}`'

    best_nodes = matched["nodes"]
    best_relationships = matched["relationships"]
    best_entity_index = matched["entity_index"]
    query_parts = []
    for index in range(len(best_nodes) - 1):
        if index == best_entity_index:
            node_str = f'(n:{selectedMainScenario_label_with_ID} {{name: "{best_nodes[best_entity_index]}"}})'
        else:
            node_str = '()'
        rel_str = f'[:{_qrel(best_relationships[index])}]'
        query_parts.append(node_str + '-' + rel_str + '->')

    if best_entity_index == len(best_nodes) - 1:
        query_parts.append(f'(n:{selectedMainScenario_label_with_ID} {{name: "{best_nodes[best_entity_index]}"}})')
    else:
        query_parts.append('()')

    match_clause = 'MATCH p=' + ''.join(query_parts)
    return f"{match_clause} RETURN p"


def fuzzy_match_paths_2(formatted_paths, input_entity, threshold=0.8):
    cleaned_entity = input_entity.strip(string.punctuation + ' ')
    matched_paths = []
    matched_entities = []

    for path_str in formatted_paths:
        entities = extract_entities_from_path(path_str)
        for node in entities:
            cleaned_node = node.strip(string.punctuation + ' ')
            sm = difflib.SequenceMatcher(None, cleaned_node, cleaned_entity)
            if sm.ratio() >= threshold:
                matched_paths.append(path_str)
                matched_entities.append(entities)
                break

    return matched_paths


def replace_with_literal(query: str) -> str:
    return re.sub(r'name:\s*".*?"', 'name: "{entityname}"', query)

