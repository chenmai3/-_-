import faiss
import jieba
import numpy as np
import torch
from transformers import AutoModel, AutoTokenizer

from ....common.neo4j_client import query_neo4j, query_new_neo4j
from ....common.paths import rule_entity_vector_store_path
from .graph_query_utils import (
    get_chinese_properties,
    normalize_rule_paths,
    record_payload,
    remove_substrings,
)
from .kdzn_rule_ent import kdzn_file_rules_kdzn_generate
from .rule_template import build_match_info, render_cypher
from .vector_matching import (
    ensure_rule_entity_vector_store,
    get_best_match,
    get_best_rule_match,
    has_faiss_store,
)


def _empty_path_result():
    return [], [], [], []


def _get_text_embedding(text, model, tokenizer):
    inputs = tokenizer(
        text,
        return_tensors="pt",
        truncation=True,
        padding=True,
        max_length=512,
    )
    with torch.no_grad():
        outputs = model(**inputs)
    return outputs.last_hidden_state[:, 0, :].squeeze().cpu().numpy()


def _get_best_phrase(fuzzy_ent, entity_list):
    split_words = {
        "的", "了", "是", "在", "有", "和", "就", "这", "个", "，", "。", "？",
        "！", "：", "；", "", " ", "（", "）", "、", "-", "“", "”",
    }
    filtered_query_words = set(jieba.cut(fuzzy_ent, cut_all=False)) - split_words
    if not filtered_query_words:
        return 0, ""

    max_score = 0
    best_entity = ""
    for entity in entity_list:
        filtered_entity_words = set(jieba.cut(entity)) - split_words
        score = len(filtered_query_words.intersection(filtered_entity_words)) / len(
            filtered_query_words
        )
        if score > max_score:
            max_score = score
            best_entity = entity
    return max_score, best_entity


def _match_with_fallback(query, candidates, model_client):
    try:
        score, candidate = get_best_rule_match(query, candidates, model_client)
        if candidate is not None:
            return score, candidate, False
    except Exception as exc:
        print(f"Embedding matching failed ({type(exc).__name__}): {exc}")
    score, candidate = _get_best_phrase(query, candidates)
    return score, candidate, True


def get_yichang(query_text, fuzzy_relation, model_name):
    """Run the legacy BERT/Faiss abnormal-event fallback for rail diagnosis."""
    tokenizer = AutoTokenizer.from_pretrained(model_name)
    model = AutoModel.from_pretrained(model_name)
    all_query_result = {}
    all_embeddings = {}
    rail_rules = kdzn_file_rules_kdzn_generate()

    for key, value in rail_rules.items():
        if value[0]["getIn4simi"]:
            query_result = query_neo4j(value[0]["getIn4simi"], kg="kdzn")
            entities = []
            for record in query_result:
                payload = record_payload(record)
                entity = [
                    payload[name]
                    for name in ("R1Name", "R2Name", "RIName")
                    if name in payload
                ]
                entities.append(entity)

            all_query_result[key] = entities
            if entities:
                all_embeddings[key] = np.array(
                    [
                        _get_text_embedding("".join(entity_names), model, tokenizer)
                        for entity_names in entities
                    ]
                )
        else:
            all_query_result[key] = []

    indexes = {}
    for key, embeddings in all_embeddings.items():
        indexes[key] = faiss.IndexFlatL2(embeddings.shape[1])
        indexes[key].add(embeddings.astype(np.float32))
    if not indexes:
        return _empty_path_result()

    query_embedding = _get_text_embedding(query_text, model, tokenizer).reshape(1, -1)
    selected_rule_group = ""
    selected_index = 0
    selected_distance = float("inf")
    for key, index in indexes.items():
        distances, indices = index.search(query_embedding.astype(np.float32), 1)
        if distances.min() < selected_distance:
            selected_distance = distances.min()
            selected_rule_group = key
            selected_index = int(indices.min())

    selected_entity = all_query_result[selected_rule_group][selected_index][-1]
    print(f"选中文件及事件：【{selected_rule_group}】--【{selected_entity}】")
    rules = rail_rules.get(selected_rule_group) or []
    if not rules:
        return _empty_path_result()
    if len(rules) == 1:
        selected_rule = rules[0]
    else:
        rule_names = [rule["rule_name"] for rule in rules]
        score, matched_rule_name = _get_best_phrase(fuzzy_relation, rule_names)
        selected_rule = next(
            (
                rule
                for rule in rules
                if score > 0 and rule["rule_name"] == matched_rule_name
            ),
            rules[0],
        )

    result_names = []
    paths = []
    path2triplet = []
    path_triplets = []
    for cypher in normalize_rule_paths(selected_rule["rule_path"]):
        cypher_result = query_neo4j(
            cypher.replace("{entityname}", selected_entity),
            kg="kdzn",
        )
        for record in cypher_result:
            path = record_payload(record)["p"]
            path_str = ""
            tail_node = ""
            result = ""
            current_triplets = []
            for index, relationship in enumerate(path.relationships):
                start_node, end_node = relationship.nodes
                start_name = start_node["name"]
                end_name = end_node["name"]
                relation_name = relationship["name"] or relationship.type
                triplet = (start_name, relation_name, end_name)
                if triplet not in path_triplets:
                    path_triplets.append(triplet)
                current_triplets.append(triplet)

                for node_name, properties in (
                    (start_name, get_chinese_properties(start_node)),
                    (end_name, get_chinese_properties(end_node)),
                ):
                    for key, value in properties.items():
                        key = "要求" if key == "requirement" else key
                        property_triplet = (node_name, key, value)
                        if property_triplet not in path_triplets:
                            path_triplets.append(property_triplet)
                        if property_triplet not in current_triplets:
                            current_triplets.append(property_triplet)

                if index == 0:
                    if start_name == selected_entity:
                        path_str = f"{start_name}-{relation_name}->{end_name}"
                        result = tail_node = end_name
                    else:
                        path_str = f"{end_name}<-{relation_name}-{start_name}"
                        result = tail_node = start_name
                elif tail_node == start_name:
                    path_str += f"-{relation_name}->{end_name}"
                    result = tail_node = end_name
                else:
                    path_str += f"<-{relation_name}-{start_name}"
                    result = tail_node = start_name

            if result and result not in result_names:
                result_names.append(result)
            if path_str and path_str not in paths:
                paths.append(path_str)
            if current_triplets and current_triplets not in path2triplet:
                path2triplet.append(current_triplets)

    return result_names, paths, path2triplet, path_triplets


def find_kdzn(
    userid,
    scene_choose,
    file_ontology,
    fuzzy_entity,
    fuzzy_relation,
    embedding,
    model_client,
):
    """Match and execute a configured rail-diagnosis graph rule."""
    del userid
    rail_rules = kdzn_file_rules_kdzn_generate(
        "ko_kdzn_rule_construct",
        scene_choose,
    )
    rules = rail_rules.get(file_ontology)
    if not rules:
        return _empty_path_result()

    embedding_unavailable = False
    if len(rules) == 1:
        selected_rule = rules[0]
        print(
            f"规则匹配：“{fuzzy_relation}”从1个规则头中匹配结果:"
            f"{selected_rule}，得分：1"
        )
    else:
        rule_names = [rule["rule_name"] for rule in rules]
        score, matched_rule_name, embedding_unavailable = _match_with_fallback(
            fuzzy_relation,
            rule_names,
            model_client,
        )
        print(
            f"规则匹配：“{fuzzy_relation}”从{len(rule_names)}个规则头中匹配结果:"
            f"{matched_rule_name}，得分：{score:.2f}"
        )
        selected_rule = next(
            (
                rule
                for rule in rules
                if score > 0 and rule["rule_name"] == matched_rule_name
            ),
            rules[0],
        )

    query_result = query_neo4j(selected_rule["getIn4simi"], kg="kdzn")
    rule_entities = []
    entity_match_info = {}
    for record in query_result:
        payload = record_payload(record)
        entity_text = "".join(
            payload[name]
            for name in ("R1Name", "R2Name", "RIName")
            if payload.get(name)
        )
        match_info = build_match_info(payload, entity_text)
        if entity_text and match_info["RIName"]:
            rule_entities.append(entity_text)
            entity_match_info[entity_text] = match_info
    if not rule_entities:
        return _empty_path_result()

    rid = selected_rule["rid"]
    print("规则对应的rid:", rid)
    vector_store_path = rule_entity_vector_store_path(rid)
    if embedding_unavailable:
        match_score, matched_entity_text = _get_best_phrase(fuzzy_entity, rule_entities)
    else:
        if not has_faiss_store(vector_store_path):
            ensure_rule_entity_vector_store(vector_store_path, rule_entities, embedding)
        match_score, matched_entity_text = get_best_match(
            fuzzy_entity,
            vector_store_path,
            embedding,
        )
        if matched_entity_text is None:
            match_score, matched_entity_text, _ = _match_with_fallback(
                fuzzy_entity,
                rule_entities,
                model_client,
            )

    match_info = entity_match_info.get(matched_entity_text)
    matched_entity = match_info.get("RIName") if match_info else None
    match_score = match_score if match_score is not None else 0.0
    print(
        f"实体段匹配：从{len(rule_entities)}个实体段中匹配结果:{matched_entity_text}"
        f"→对应检索实体:{matched_entity}，得分：{match_score:.2f}"
    )
    if matched_entity == file_ontology:
        match_score = 1.1
    if match_score < 0.2:
        return _empty_path_result()

    result_names = []
    paths = []
    path2triplet = []
    path_triplets = []
    if matched_entity is None:
        return result_names, paths, path2triplet, path_triplets

    for cypher in normalize_rule_paths(selected_rule["rule_path"]):
        cypher_runtime = render_cypher(cypher, match_info, fuzzy_entity)
        print("cypher_runtime:", cypher_runtime)
        for record in query_new_neo4j(cypher_runtime, kg="kdzn"):
            path = record_payload(record)
            current_triplets = []
            for relationship in path.relationships:
                start_node, end_node = relationship.nodes
                start_name = start_node["name"]
                end_name = end_node["name"]
                relation_name = relationship["name"] or relationship.type
                if relation_name in {"kedazhineng", "KedaIntelligent", "kdzn"}:
                    relation_name = relationship["edge_name"]
                if relation_name is None:
                    relation_name = relationship["type"]
                if isinstance(relation_name, str) and relation_name.startswith("包含-"):
                    relation_name = "包含"

                triplet = (start_name, relation_name, end_name)
                if triplet not in path_triplets:
                    path_triplets.append(triplet)
                current_triplets.append(triplet)
                for node_name, properties in (
                    (start_name, get_chinese_properties(start_node)),
                    (end_name, get_chinese_properties(end_node)),
                ):
                    for key, value in properties.items():
                        key = "要求" if key == "requirement" else key
                        property_triplet = (node_name, key, value)
                        if property_triplet not in path_triplets:
                            path_triplets.append(property_triplet)
                        if property_triplet not in current_triplets:
                            current_triplets.append(property_triplet)

            if not current_triplets:
                continue
            first_triplet = current_triplets[0]
            if len(current_triplets) == 1:
                path_str = f"-[{first_triplet[1]}]->{first_triplet[2]}"
                tail_node = first_triplet[2]
            else:
                second_triplet = current_triplets[1]
                if first_triplet[0] in {second_triplet[0], second_triplet[2]}:
                    path_str = (
                        f"{first_triplet[2]}<-[{first_triplet[1]}]-"
                        f"{first_triplet[0]}"
                    )
                    tail_node = first_triplet[0]
                else:
                    path_str = (
                        f"{first_triplet[0]}-[{first_triplet[1]}]->"
                        f"{first_triplet[2]}"
                    )
                    tail_node = first_triplet[2]

            for triplet in current_triplets[1:]:
                if tail_node == triplet[0]:
                    path_str += f"-[{triplet[1]}]->{triplet[2]}"
                    tail_node = triplet[2]
                else:
                    path_str += f"<-[{triplet[1]}]-{triplet[0]}"
                    tail_node = triplet[0]

            if tail_node not in result_names:
                result_names.append(tail_node)
            if path_str not in paths:
                paths.append(path_str)
            if current_triplets not in path2triplet:
                path2triplet.append(current_triplets)

    return result_names, remove_substrings(paths), path2triplet, path_triplets


def all_paths_from_entity(head, max_hop=5):
    """Return the fixed rail diagnostic chain starting from an entity."""
    query = """
        MATCH p=()-[:数据]->(n:kdzn {name: $entityname})
              -[:分析条件]->()-[:输出结果]->()-[:可能原因]->()
        RETURN p
    """
    formatted_paths = []
    paths_tris = []
    result = query_new_neo4j(
        query,
        parameters={"entityname": head},
        kg="kdzn",
    )
    print(result)
    for record in result:
        path = record_payload(record)["p"]
        nodes = path.nodes
        relationships = path.relationships
        path_str = str(nodes[0]["name"])
        current_triplets = []
        for index, relationship in enumerate(relationships):
            relation_type = relationship.type
            direction, arrow = (
                ("-", "->")
                if relationship.start_node == nodes[index]
                else ("<-", "-")
            )
            path_str += (
                f"{direction}{relation_type}{arrow}{nodes[index + 1]['name']}"
            )
            current_triplets.append(
                [
                    relationship.start_node["name"],
                    relation_type,
                    relationship.end_node["name"],
                ]
            )
        formatted_paths.append(path_str)
        paths_tris.append(current_triplets)
    return formatted_paths, paths_tris
