import concurrent.futures
import json
import re
from dataclasses import dataclass
from threading import Lock
from typing import List, Tuple

from ....common.neo4j_client import query_new_neo4j
from ....common.paths import entity_vector_store_path
from ..llm_clients import call_qwen_messages
from .general_query_state import (
    EMPTY_RES,
    GeneralQueryCache,
    SearchResult,
    normalize_matched_entities,
)
from .graph_query_utils import get_chinese_properties, han2pinyin_concat
from .vector_matching import get_top_matches


@dataclass(frozen=True)
class TogSearchContext:
    label_with_id: str
    file_ontology: str
    scene_choose: str
    rewritten_query: str
    is_multi_turn: bool
    top_k: int
    fuzzy_entity: str
    max_rounds: int


def _extract_json_object(raw_text):
    if not raw_text:
        return {}
    match = re.search(r"\{.*?\}", str(raw_text), re.DOTALL)
    if not match:
        return {}
    try:
        value = json.loads(match.group(0))
    except (TypeError, ValueError):
        return {}
    return value if isinstance(value, dict) else {}


def _call_tog_qwen(prompt):
    answer = call_qwen_messages([{"role": "user", "content": prompt}])
    return answer or ""


def _resolve_cached_path(raw_text):
    result = _extract_json_object(raw_text).get("result")
    return str(result or "TOG")


def _parse_tog_selection(raw_text, path_count):
    data = _extract_json_object(raw_text)
    ids = data.get("selected_ids", [])
    if isinstance(ids, list):
        selected_indices = [int(index) for index in ids if str(index).isdigit()]
    elif isinstance(ids, (int, str)) and str(ids).isdigit():
        selected_indices = [int(ids)]
    else:
        selected_indices = []
    selected_indices = [
        index for index in selected_indices if 0 <= index < path_count
    ]
    if not selected_indices:
        selected_indices = list(range(path_count))
    return data.get("result") == "over", selected_indices, data


_GRAPH_LABEL_PATTERN = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*$")


def _validate_graph_label(label):
    label = str(label or "")
    if not _GRAPH_LABEL_PATTERN.fullmatch(label):
        raise ValueError(f"非法图谱标签: {label!r}")
    return label


def _build_initial_path_query(label):
    label = _validate_graph_label(label)
    return f"""
        MATCH p = (n:{label} {{name: $match_entity}})-[*1]->()
        RETURN p

        UNION ALL

        MATCH p = ()-[*1]->(n:{label} {{name: $match_entity}})
        RETURN p
    """


def get_path_direction(
    selected_path_str: str,
    top_entities: List[Tuple[float, str]],
) -> str:
    match = re.match(r"(.+?)-\[(.+?)\]->(.+)", selected_path_str.strip())
    if not match:
        raise ValueError(f"无法解析单跳路径格式：{selected_path_str}")
    node1, _relation, node2 = (part.strip() for part in match.groups())

    def extract_core_name(text):
        text = str(text).strip()
        match = re.match(r"^([a-zA-Z\u4e00-\u9fa5]+)", text)
        if match:
            return match.group(1)
        for separator in ("(", " - ", "，", "。"):
            text = text.split(separator, 1)[0]
        return text

    core_names = [extract_core_name(text) for _, text in top_entities]
    for name in core_names:
        if node1 == name:
            return "backward"
        if node2 == name:
            return "forward"
    raise ValueError(
        f"路径 {selected_path_str!r} 的两端 ({node1}, {node2}) "
        f"未匹配任何候选实体：{core_names}"
    )


def query_path_extend_one_hop_forward(label_with_id, path_str, scene_choose):
    nodes = [
        node.strip()
        for node in re.split(r"-\[.*?\]->", path_str.strip())
        if node.strip()
    ]
    if not nodes:
        raise ValueError(f"无法解析路径：{path_str}")

    label_with_id = _validate_graph_label(label_with_id)
    parameters = {}
    parts = ["(m)-[]->"]
    for index, name in enumerate(nodes):
        parameter_name = f"path_node_{index}"
        parameters[parameter_name] = name
        parts.append(
            f"(n{index}:{label_with_id} {{name: ${parameter_name}}})"
        )
        if index < len(nodes) - 1:
            parts.append("-[]->")
    query = f"""
    MATCH p = {''.join(parts)}
    RETURN p
    LIMIT 50
    """
    return query_path(query, scene_choose, parameters=parameters)


def query_path_extend_one_hop_backward(label_with_id, path_str, scene_choose):
    nodes = [
        node.strip()
        for node in re.split(r"-\[.*?\]->", path_str.strip())
        if node.strip()
    ]
    if not nodes:
        raise ValueError(f"无法解析路径：{path_str}")

    label_with_id = _validate_graph_label(label_with_id)
    parameters = {}
    parts = []
    for index, name in enumerate(nodes):
        parameter_name = f"path_node_{index}"
        parameters[parameter_name] = name
        parts.append(
            f"(n{index}:{label_with_id} {{name: ${parameter_name}}})"
        )
        if index < len(nodes) - 1:
            parts.append("-[]->")
    parts.append("-[]->(m)")
    query = f"""
    MATCH p = {''.join(parts)}
    RETURN p
    LIMIT 50
    """
    return query_path(query, scene_choose, parameters=parameters)


def query_path(query, selected_main_scenario, parameters=None):
    if not query:
        return [], [], [], []

    print(f"执行查询: {query}")
    kg = "jiapu" if selected_main_scenario == "家谱主题问答" else ""
    cypher_result = query_new_neo4j(query, parameters=parameters, kg=kg)
    raw_records = []
    seen_paths = set()
    path_triplets = []

    for record in cypher_result:
        path = record["p"]
        for node in path.nodes:
            node_name = node.get("name", str(node))
            for key, value in get_chinese_properties(node).items():
                key = "要求" if key == "requirement" else key
                triplet = (node_name, key, value)
                if triplet not in path_triplets:
                    path_triplets.append(triplet)

        nodes = list(path.nodes)
        relationships = list(path.relationships)
        if not nodes:
            continue
        parts = [nodes[0].get("name", str(nodes[0]))]
        current_triplets = []
        for index, relationship in enumerate(relationships):
            relation_type = relationship.type
            try:
                if (
                    relation_type in {"kedazhineng", "KedaIntelligent", "kdzn"}
                    and "edge_name" in relationship
                ):
                    relation_type = relationship.get("edge_name") or relation_type
            except TypeError:
                pass
            if isinstance(relation_type, str) and relation_type.startswith("包含-"):
                relation_type = "包含"

            current = nodes[index]
            following = nodes[index + 1]
            current_name = current.get("name", str(current))
            following_name = following.get("name", str(following))
            start_name = relationship.nodes[0].get(
                "name", str(relationship.nodes[0])
            )
            end_name = relationship.nodes[1].get(
                "name", str(relationship.nodes[1])
            )
            if current_name == start_name and following_name == end_name:
                parts.append(f"-[{relation_type}]->")
            else:
                parts.append(f"<-[{relation_type}]-")
            parts.append(following_name)
            triplet = (current_name, relation_type, following_name)
            if triplet not in path_triplets:
                path_triplets.append(triplet)
            current_triplets.append(triplet)

        path_str = "".join(parts)
        if path_str not in seen_paths:
            seen_paths.add(path_str)
            raw_records.append(
                {
                    "name": nodes[-1].get("name", str(nodes[-1])),
                    "path": path_str,
                    "p2t": current_triplets,
                }
            )

    raw_records.sort(key=lambda record: len(record["path"]), reverse=True)
    final_records = []
    kept_paths = set()
    for record in raw_records:
        current_path = record["path"]
        if any(
            current_path in kept and current_path != kept
            for kept in kept_paths
        ):
            continue
        final_records.append(record)
        kept_paths.add(current_path)

    return (
        [record["name"] for record in final_records],
        [record["path"] for record in final_records],
        [record["p2t"] for record in final_records],
        path_triplets,
    )


_CACHE_PROMPT = """你是图谱路径选择助手。判断历史路径能否回答用户问题。
能回答时输出 {{"result":"over"}}；需要沿某条历史路径继续时输出
{{"result":"完整路径"}}；历史路径无关时输出 {{"result":"TOG"}}。
只输出 JSON。
用户问题：__query__
历史路径：
__path__
"""


_PATH_SELECTION_PROMPT = """你是图谱路径推理助手。根据用户问题筛选能够回答问题的候选路径。
优先匹配问题意图与路径最后一个关系。具体答案已经出现时 result 为 over；
终点仍是中间概念、需要展开时 result 为 continue；无匹配路径时 selected_ids 为空。
只输出 JSON：{{"result":"over或continue","selected_ids":[路径ID]}}
用户问题："{query}"
候选路径：
{path_context}
"""


def run_tog_search(
    reason,
    *,
    context: TogSearchContext,
    cache_manager: GeneralQueryCache,
    embedding,
    event_queue,
):
    print(f"进入TOG图谱探索，原因：{reason}")
    top_k = max(1, int(context.top_k))
    cache = cache_manager.get_paths()
    result_list = []
    matched_entities = []
    cache_decision = ""

    if cache:
        prompt = _CACHE_PROMPT.replace("__query__", context.rewritten_query)
        prompt = prompt.replace("__path__", "\n".join(map(str, cache)))
        answer = _call_tog_qwen(prompt)
        print("缓存路径判断:", answer)
        cache_decision = _resolve_cached_path(answer)

    if (
        context.is_multi_turn
        and cache
        and cache_decision not in {"TOG", "over"}
    ):
        cached_result = cache_manager.get_result_by_path(cache_decision)
        if cached_result is not None:
            result_list.append(
                (
                    cached_result.result_names,
                    cached_result.paths,
                    cached_result.path2triplet,
                    cached_result.path_triplets,
                )
            )
            matched_entities = cached_result.matched_entities

    if cache_decision == "over":
        results = cache_manager.get_results(is_over=True)
        while len(results) < top_k:
            results.append(EMPTY_RES)
        return results[:top_k]

    if not result_list:
        ontology = han2pinyin_concat(context.file_ontology)
        vector_path = entity_vector_store_path(context.label_with_id, ontology)
        matched_entities = get_top_matches(
            context.fuzzy_entity,
            vector_path,
            embedding,
        )
        print("TOG入口实体:", matched_entities)
        query = _build_initial_path_query(context.label_with_id)
        for _score, entity_name in matched_entities:
            result_list.append(
                query_path(
                    query,
                    context.scene_choose,
                    parameters={"match_entity": entity_name},
                )
            )

    while len(result_list) < top_k:
        result_list.append(([], [], [], []))
    event_queue.put(
        "data: <PrOSpLiT>系统在该场景下没有检索到规则</PrOSpLiT>\n\n"
    )

    printed_rounds = set()
    printed_rounds_lock = Lock()
    print_lock = Lock()

    def explore_candidate(
        result_names,
        paths,
        path2triplet,
        path_triplets,
        *,
        entity_tag,
        candidate_index,
        current_match,
    ):
        rounds_left = max(1, int(context.max_rounds))
        direction = None
        is_over = False
        while rounds_left:
            path_context = "\n".join(
                f"【ID: {index}】: {path}"
                for index, path in enumerate(paths)
            )
            prompt = _PATH_SELECTION_PROMPT.format(
                query=context.rewritten_query,
                path_context=path_context,
            )
            answer = _call_tog_qwen(prompt)
            is_over, selected_indices, data = _parse_tog_selection(
                answer,
                len(paths),
            )
            round_index = context.max_rounds - rounds_left + 1
            model_output = (
                json.dumps(data, ensure_ascii=False)
                if data
                else answer[:100] or "<empty>"
            )
            with print_lock:
                print(
                    f"[Entity#{candidate_index} | {entity_tag}] "
                    f"R{round_index} LLM={model_output} -> "
                    f"over={is_over}, select={selected_indices}"
                )
            with printed_rounds_lock:
                if round_index not in printed_rounds:
                    event_queue.put(
                        "data: <PrOSpLiT>"
                        f"正在进行图思考第{round_index}轮路径选择"
                        "</PrOSpLiT>\n\n"
                    )
                    printed_rounds.add(round_index)

            current_names = [result_names[index] for index in selected_indices]
            current_paths = [paths[index] for index in selected_indices]
            current_p2t = [
                path2triplet[index]
                for index in selected_indices
                if index < len(path2triplet)
            ]
            if is_over:
                return SearchResult(
                    True,
                    current_names,
                    current_paths,
                    current_p2t,
                    path_triplets,
                    current_match,
                )
            if rounds_left == 1:
                return SearchResult(
                    False,
                    current_names,
                    current_paths,
                    current_p2t,
                    path_triplets,
                    current_match,
                )

            next_names, next_paths, next_p2t, next_triplets = [], [], [], []
            all_dead_ends = True
            for subset_index, current_path in enumerate(current_paths):
                try:
                    if direction is None:
                        direction = get_path_direction(
                            current_path,
                            matched_entities,
                        )
                except (TypeError, ValueError):
                    direction = "backward"

                if direction == "forward":
                    expanded = query_path_extend_one_hop_forward(
                        context.label_with_id,
                        current_path,
                        context.scene_choose,
                    )
                else:
                    expanded = query_path_extend_one_hop_backward(
                        context.label_with_id,
                        current_path,
                        context.scene_choose,
                    )
                names, expanded_paths, p2t, triplets = expanded
                if not expanded_paths:
                    next_names.append(current_names[subset_index])
                    next_paths.append(current_path)
                    if subset_index < len(current_p2t):
                        next_p2t.append(current_p2t[subset_index])
                else:
                    all_dead_ends = False
                    next_names.extend(names)
                    next_paths.extend(expanded_paths)
                    next_p2t.extend(p2t)
                    next_triplets.extend(triplets)

            if all_dead_ends or not next_paths:
                return SearchResult(
                    False,
                    next_names or current_names,
                    next_paths or current_paths,
                    next_p2t or current_p2t,
                    path_triplets,
                    current_match,
                )
            result_names = next_names
            paths = next_paths
            path2triplet = next_p2t
            path_triplets = next_triplets
            rounds_left -= 1

        return SearchResult(
            is_over,
            result_names,
            paths,
            path2triplet,
            path_triplets,
            current_match,
        )

    def explore_safely(result, *, entity_tag, candidate_index, current_match):
        normalized_match = normalize_matched_entities(current_match)
        try:
            if not isinstance(result, (list, tuple)) or len(result) != 4:
                return SearchResult(False, [], [], [], [], normalized_match)
            return explore_candidate(
                *result,
                entity_tag=entity_tag,
                candidate_index=candidate_index,
                current_match=normalized_match,
            )
        except Exception as error:
            with print_lock:
                print(
                    f"[Entity#{candidate_index} | {entity_tag}] "
                    f"TOG探索失败: {error}"
                )
            return SearchResult(False, [], [], [], [], normalized_match)

    entity_tags = [name for _, name in matched_entities]
    while len(entity_tags) < top_k:
        entity_tags.append(f"cand{len(entity_tags)}")

    with concurrent.futures.ThreadPoolExecutor(max_workers=top_k) as executor:
        futures = []
        for index in range(top_k):
            current_match = (
                matched_entities[index]
                if index < len(matched_entities)
                else None
            )
            futures.append(
                executor.submit(
                    explore_safely,
                    result_list[index],
                    entity_tag=entity_tags[index],
                    candidate_index=index,
                    current_match=current_match,
                )
            )
        return [future.result() for future in futures]
