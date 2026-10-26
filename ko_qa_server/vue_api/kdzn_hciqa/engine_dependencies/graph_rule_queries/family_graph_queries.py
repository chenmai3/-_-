import re
import threading
import time
from dataclasses import dataclass, field

import dashscope

from ....common.neo4j_client import query_new_neo4j
from ...shared import load_config
from .kdzn_rule_ent import kdzn_file_rules_kdzn_generate, query_by_parentheses_chars


@dataclass
class FamilyRelationState:
    people_list_1: list[str] = field(default_factory=list)
    people_list_2: list[str] = field(default_factory=list)
    fuzzy_entity_1: str = ""
    fuzzy_entity_2: str = ""
    zibei_1: str = ""
    zibei_2: str = ""
    updated_at: float = field(default_factory=time.monotonic)
    lock: object = field(default_factory=threading.RLock, repr=False)


class FamilyRelationStateStore:
    def __init__(self, ttl_seconds=3600):
        self._ttl_seconds = ttl_seconds
        self._states = {}
        self._lock = threading.RLock()

    @staticmethod
    def _key(session_id):
        return str(session_id or "__default__")

    def _remove_expired(self, now):
        expired = [
            key
            for key, state in self._states.items()
            if now - state.updated_at > self._ttl_seconds
        ]
        for key in expired:
            self._states.pop(key, None)

    def get(self, session_id):
        now = time.monotonic()
        key = self._key(session_id)
        with self._lock:
            self._remove_expired(now)
            state = self._states.get(key)
            if state is None:
                state = FamilyRelationState()
                self._states[key] = state
            state.updated_at = now
            return state

    def clear(self, session_id):
        with self._lock:
            self._states.pop(self._key(session_id), None)


family_relation_states = FamilyRelationStateStore()


def query_entity_info(entityname):
    """Return all matching family-tree node properties as display text."""
    query_result = query_new_neo4j(
        "MATCH (n:huaputong) WHERE n.name = $entityname RETURN n",
        parameters={"entityname": entityname},
        kg="jiapu",
    )
    if not query_result:
        return f"在图谱中未查询到实体：{entityname}"

    result_texts = []
    for record in query_result:
        node = record["n"]
        properties = node._properties if hasattr(node, "_properties") else dict(node)
        prop_str = ", ".join(f"{key}: {value}" for key, value in properties.items())
        result_texts.append(f"【实体信息】 {prop_str}")
    return "\n".join(result_texts)


def query_relationship(entityname, relationship, rules):
    result_names = []
    result_des_n = []
    result_des_b = []
    paths = []
    path_triplets = []
    path2triplet = []
    for rule in rules:
        rule_path = rule.get("rule_path")
        query = rule_path[0].replace("{entityname}", entityname)
        print(query)
        query_result = query_new_neo4j(query, kg="jiapu")
        print("query_neo4j_res", query_result)
        for record in query_result:
            path = record["p"]
            relationships = list(path.relationships)
            path_triplet = []
            path_str = ""
            tail_node = ""
            result = ""
            des_n = path.start_node["des"]
            des_b = path.end_node["des"]
            for index, relationship_data in enumerate(relationships):
                nodes = relationship_data.nodes
                start_node = nodes[0]["name"]
                end_node = nodes[1]["name"]
                relation = relationship_data["name"] or relationship_data.type
                path_triplet.append((start_node, relation, end_node))
                if (start_node, relation, end_node) not in path_triplets:
                    path_triplets.append((start_node, relation, end_node))

                if index == 0:
                    if start_node == entityname:
                        path_str += f"{start_node}-{relation}->{end_node}"
                        result = end_node
                        tail_node = end_node
                    else:
                        path_str += f"{end_node}<-{relation}-{start_node}"
                        result = start_node
                        tail_node = start_node
                elif tail_node == start_node:
                    path_str += f"-{relation}->{end_node}"
                    tail_node = end_node
                    result = end_node
                else:
                    path_str += f"<-{relation}-{start_node}"
                    tail_node = start_node
                    result = start_node

            if des_n not in result_des_n:
                result_des_n.append(des_n)
            if des_b not in result_des_b:
                result_des_b.append(des_b)
            if result not in result_names:
                result_names.append(result)
            if path_str not in paths:
                paths.append(path_str)
            if path_triplet not in path2triplet:
                path2triplet.append(path_triplet)
    return result_names, paths, result_des_n, result_des_b, path2triplet, path_triplets


def query_relationship_zibei(entityname1, entityname2, rule_path):
    result_names = []
    result_des_n = []
    result_des_b = []
    paths = []
    path_triplets = []
    path2triplet = []
    if not rule_path:
        return result_names, paths, result_des_n, result_des_b, path2triplet, path_triplets, [], []

    query = rule_path.replace("{entityname}", entityname1, 1)
    query = query.replace("{entityname}", entityname2, 1)
    print(query)
    query_result = query_new_neo4j(query, kg="jiapu")
    zibei_first = ""
    zibei_second = ""
    print("query_neo4j_res", query_result)
    for record in query_result:
        if record["zibei_1"]:
            zibei_first = record["zibei_1"]
        if record["zibei_2"]:
            zibei_second = record["zibei_2"]

        path = record["p"]
        relationships = list(path.relationships)
        path_triplet = []
        path_str = ""
        tail_node = ""
        result = ""
        des_n = path.start_node["des"]
        des_b = path.end_node["des"]
        for index, relationship_data in enumerate(relationships):
            nodes = relationship_data.nodes
            start_node = nodes[0]["name"]
            end_node = nodes[1]["name"]
            relation = relationship_data["name"] or relationship_data.type
            path_triplet.append((start_node, relation, end_node))
            if (start_node, relation, end_node) not in path_triplets:
                path_triplets.append((start_node, relation, end_node))

            if index == 0:
                if start_node == entityname1:
                    path_str += f"{start_node}-{relation}->{end_node}"
                    result = end_node
                    tail_node = end_node
                else:
                    path_str += f"{end_node}<-{relation}-{start_node}"
                    result = start_node
                    tail_node = start_node
            elif tail_node == start_node:
                path_str += f"-{relation}->{end_node}"
                tail_node = end_node
                result = end_node
            else:
                path_str += f"<-{relation}-{start_node}"
                tail_node = start_node
                result = start_node

        if des_n not in result_des_n:
            result_des_n.append(des_n)
        if des_b not in result_des_b:
            result_des_b.append(des_b)
        if result not in result_names:
            result_names.append(result)
        if path_str not in paths:
            paths.append(path_str)
        if path_triplet not in path2triplet:
            path2triplet.append(path_triplet)
    return (
        result_names,
        paths,
        result_des_n,
        result_des_b,
        path2triplet,
        path_triplets,
        zibei_first,
        zibei_second,
    )


def extract_valid_zibei_strict(record_list):
    """Return the first single-Chinese-character generation marker."""
    for record in record_list:
        value = record["ZIBEI"]
        if (
            value
            and not value.isdigit()
            and value != "不详"
            and len(value.strip()) == 1
            and "\u4e00" <= value <= "\u9fff"
        ):
            return value
    return ""


def extract_person_desc_snippet(person_text, default=""):
    match = re.search(r"描述:\s*(.{1,20})", person_text or "")
    return match.group(1) if match else default


def _rerank_description(query, documents):
    documents = [document for document in documents if document]
    if not query or not documents:
        return query

    qwen_config = load_config()["small_models"]["qwen"]
    response = dashscope.TextReRank.call(
        model="gte-rerank-v2",
        query=query,
        api_key=qwen_config["api_key"],
        base_http_api_url=qwen_config["base_url"],
        documents=documents,
        top_n=10,
        return_documents=True,
        instruct="Given a web search query, retrieve relevant passages that answer the query.",
    )
    try:
        return response.output.results[0]["document"]["text"]
    except Exception:
        return query


def _person_summaries(records):
    summaries = []
    for record in records:
        person = dict(record.get("n"))
        description = person.get("des", "无描述")
        summaries.append(
            f"姓名: {person.get('name')}, 字辈: {person.get('zibei')}, 描述: {description[:15]}..."
        )
    return summaries


def _query_people(name):
    return query_new_neo4j(
        "MATCH (n:huaputong) WHERE n.name = $name RETURN n",
        parameters={"name": name},
        kg="jiapu",
    )


def _query_person_by_description(name, description):
    return query_new_neo4j(
        "MATCH (n:huaputong) "
        "WHERE n.name = $name AND n.des CONTAINS $description RETURN n",
        parameters={"name": name, "description": description},
        kg="jiapu",
    )


def _query_zibei(name):
    return query_new_neo4j(
        "MATCH (n:huaputong) WHERE n.name = $name RETURN n.zibei AS ZIBEI",
        parameters={"name": name},
        kg="jiapu",
    )


def find_kograph_zibei(
    peo_1,
    peo_2,
    anchor1_generation,
    anchor2_generation,
    anchor1_des,
    anchor2_des,
    model_client,
    session_id=None,
):
    state = family_relation_states.get(session_id)
    with state.lock:
        return _find_kograph_zibei(
            peo_1,
            peo_2,
            anchor1_generation,
            anchor2_generation,
            anchor1_des,
            anchor2_des,
            model_client,
            state,
        )


def _find_kograph_zibei(
    peo_1,
    peo_2,
    anchor1_generation,
    anchor2_generation,
    anchor1_des,
    anchor2_des,
    model_client,
    state,
):
    del model_client
    people_list_1 = list(state.people_list_1)
    people_list_2 = list(state.people_list_2)
    fuzzy_entity_1 = state.fuzzy_entity_1
    fuzzy_entity_2 = state.fuzzy_entity_2
    zibei_1 = state.zibei_1
    zibei_2 = state.zibei_2

    def persist(result):
        state.people_list_1 = people_list_1
        state.people_list_2 = people_list_2
        state.fuzzy_entity_1 = fuzzy_entity_1
        state.fuzzy_entity_2 = fuzzy_entity_2
        state.zibei_1 = zibei_1
        state.zibei_2 = zibei_2
        state.updated_at = time.monotonic()
        return result

    if anchor2_des or anchor1_des:
        if anchor1_des:
            if people_list_1:
                descriptions = [extract_person_desc_snippet(person) for person in people_list_1 + people_list_2]
                anchor1_des = _rerank_description(anchor1_des, descriptions)
            records = _query_person_by_description(peo_1, anchor1_des)
            if len(records) == 1:
                people_list_1 = _person_summaries(records)
                people_list_2 = []
                zibei_1 = dict(records[0].get("n")).get("zibei")
        else:
            fuzzy_entity_1 = peo_1

        if anchor2_des:
            if people_list_2:
                descriptions = [extract_person_desc_snippet(person) for person in people_list_1 + people_list_2]
                anchor2_des = _rerank_description(anchor2_des, descriptions)
            records = _query_person_by_description(peo_2, anchor2_des)
            if len(records) == 1:
                people_list_1 = []
                people_list_2 = _person_summaries(records)
                zibei_2 = dict(records[0].get("n")).get("zibei")
        else:
            fuzzy_entity_2 = peo_2

        rules = query_by_parentheses_chars(zibei_1, zibei_2)
        rule_name = "" if not rules else rules[0]["rulename"]
        if zibei_1 == zibei_2:
            rule_name = f"{fuzzy_entity_1}和{fuzzy_entity_2}的字辈都是{zibei_1},是同辈关系。"
        else:
            prefix = (
                f"{fuzzy_entity_1}的字辈是{zibei_1},{fuzzy_entity_2}的字辈是{zibei_2}，"
                f"{fuzzy_entity_1}是{fuzzy_entity_2}的"
            )
            rule_name = prefix + (rule_name or "未知关系，根据已有的字辈规则不能回答这个问题。")
        return persist(([], [], [], [], rule_name, people_list_1, people_list_2))

    fuzzy_entity_1 = peo_1
    fuzzy_entity_2 = peo_2
    zibei_1 = anchor1_generation
    zibei_2 = anchor2_generation
    people_records_1 = _query_people(fuzzy_entity_1)
    people_records_2 = _query_people(fuzzy_entity_2)
    shortest_path_rule = (
        'MATCH (a:huaputong {name:"{entityname}"}), '
        '(b:huaputong {name:"{entityname}"}), '
        "p = shortestPath((a)-[*1..5]-(b)) "
        "RETURN p, a.zibei AS zibei_1, b.zibei AS zibei_2 LIMIT 1"
    )
    result = query_relationship_zibei(fuzzy_entity_1, fuzzy_entity_2, shortest_path_rule)
    result_names, paths, _, _, path2triplet, path_triplets, zibei_1, zibei_2 = result

    if len(people_records_1) > 1 or len(people_records_2) > 1:
        people_list_1 = _person_summaries(people_records_1)
        people_list_2 = _person_summaries(people_records_2)

    if result_names:
        rules = query_by_parentheses_chars(zibei_1, zibei_2)
        rule_name = "" if not rules else rules[0]["rulename"]
        prefix = (
            f"{fuzzy_entity_1}的字辈是{zibei_1},{fuzzy_entity_2}的字辈是{zibei_2}，"
            f"{fuzzy_entity_1}是{fuzzy_entity_2}的"
        )
        rule_name = prefix + (rule_name or "未知关系，根据已有的字辈规则不能回答这个问题。")
        return persist(
            (result_names, paths, path2triplet, path_triplets, rule_name, people_list_1, people_list_2)
        )

    if not people_records_1 and not people_records_2:
        zibei_1 = anchor1_generation
        zibei_2 = anchor2_generation

    query_result_1 = _query_zibei(fuzzy_entity_1)
    query_result_2 = _query_zibei(fuzzy_entity_2)
    zibei_1 = extract_valid_zibei_strict(query_result_1) if query_result_1 else anchor1_generation
    zibei_2 = extract_valid_zibei_strict(query_result_2) if query_result_2 else anchor2_generation
    rules = query_by_parentheses_chars(zibei_1, zibei_2)
    rule_path = "" if not rules else rules[0]["rulepath"]
    rule_name = "" if not rules else rules[0]["rulename"]
    prefix = (
        f"{fuzzy_entity_1}的字辈是{zibei_1},{fuzzy_entity_2}的字辈是{zibei_2}，"
        f"{fuzzy_entity_1}是{fuzzy_entity_2}的"
    )
    rule_name = prefix + (rule_name or "未知关系，根据已有的字辈规则不能回答这个问题。")
    result = query_relationship_zibei(fuzzy_entity_1, fuzzy_entity_2, rule_path)
    result_names, paths, _, _, path2triplet, path_triplets, _, _ = result
    return persist(
        (result_names, paths, path2triplet, path_triplets, rule_name, people_list_1, people_list_2)
    )


def find_kograph(fuzzy_entity, fuzzy_relation, model_client):
    del model_client
    try:
        if fuzzy_relation == "信息":
            entity_infos = query_entity_info(fuzzy_entity)
            return [], [], {}, [], entity_infos

        rules_by_name = kdzn_file_rules_kdzn_generate("ko_kdzn_rule_construct", "家谱问答")
        rules = rules_by_name.get(fuzzy_relation)
        if not rules:
            print(f"规则匹配：“{fuzzy_relation}”-未匹配到任何规则")
            return [], [], {}, [], ""

        print(f"规则匹配：“{fuzzy_relation}”-规则匹配结果:{rules[0]['rule_name']}")
        result_names, paths, _, _, path2triplet, path_triplets = query_relationship(
            fuzzy_entity,
            rules[0]["rule_name"],
            rules,
        )
        return result_names, paths, path2triplet, path_triplets, ""
    except IndexError as exc:
        print(f"规则匹配异常：规则列表为空，无法获取第一条规则 - 错误详情：{exc}")
        return [], [], {}, [], ""
    except Exception as exc:
        print(f"查询图谱异常：{exc}")
        return [], [], {}, [], ""
