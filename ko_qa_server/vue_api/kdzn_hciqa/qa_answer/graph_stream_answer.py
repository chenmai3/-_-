import json
import queue
import re
import threading
import time
import traceback
from types import SimpleNamespace

from openai import OpenAI
from pypinyin import lazy_pinyin

from ..shared import (
    QA_history,
    Result,
    EMPTY_MODEL_RESPONSE_MESSAGE,
    SENSITIVE_ERROR_MESSAGE,
    USER_ERROR_MESSAGE,
    connect_to_db,
    create_answer_stream_with_fallback,
    get_model,
    is_reasoning_model,
    is_thinking_selection,
    thinking_extra_body,
    kdzn_history,
    load_config,
    load_history_qa,
    sse_error,
    sse_message,
    stream_response,
    update_sql_history,
)


def han2pinyin_concat(text: str) -> str:
    # ko4csg_hci 内部函数：由主题中文名生成图谱 label 前缀。
    return "".join(lazy_pinyin(text or ""))


def jiapu_to_excel_markdown(triples_list):
    # ko4csg_hci 内部函数：家谱问答场景的三元组表格转换。
    if not triples_list:
        return ""

    subjects = set()
    relations = set()
    triples_dict = {}

    for triple_pair in triples_list:
        for triple in triple_pair:
            subject, relation, obj = triple
            subjects.add(subject)
            relations.add(relation)
            triples_dict.setdefault(subject, {}).setdefault(relation, set()).add(obj)

    subjects_sorted = sorted(list(subjects))
    relations_sorted = sorted(list(relations))

    markdown = "|| " + " | ".join(relations_sorted) + " |\n"
    markdown += "|------|" + "|".join(["------" for _ in relations_sorted]) + "|\n"
    for subject in subjects_sorted:
        row = f"| {subject} |"
        for relation in relations_sorted:
            values_set = triples_dict.get(subject, {}).get(relation, set())
            value = "、".join(sorted(list(values_set))) if values_set else ""
            row += f" {value} |"
        markdown += row + "\n"
    return markdown


def triplets_to_markdown_table(triplets):
    # ko4csg_hci 内部函数：普通知识图谱路径三元组转 Markdown 表格。
    def extract_rows(nested_triplets):
        rows = []
        for item in nested_triplets:
            if not isinstance(item, list):
                continue
            row_data = {}
            seen_triplets = set()
            for triplet in item:
                if not isinstance(triplet, (tuple, list)) or len(triplet) != 3:
                    continue
                subject, predicate, obj = triplet
                predicate = str(predicate).strip()
                obj = str(obj).strip()
                triple_key = (subject, predicate, obj)
                if triple_key in seen_triplets:
                    continue
                seen_triplets.add(triple_key)
                if predicate in row_data:
                    existing_values = [x.strip() for x in row_data[predicate].split(", ")]
                    if obj not in existing_values:
                        row_data[predicate] += f", {obj}"
                else:
                    row_data[predicate] = obj
            if row_data and row_data not in rows:
                rows.append(row_data)
        return rows

    def get_all_columns(rows):
        columns = []
        seen_columns = set()
        for row in rows:
            for column in row.keys():
                if column not in seen_columns:
                    seen_columns.add(column)
                    columns.append(column)
        return columns

    def format_cell_content(content, max_length=100):
        if not content:
            return ""
        content_str = str(content).strip()
        formatted_content = content_str.replace("\n", "<br>")
        if len(content_str) > max_length:
            return f"<details><summary>点击展开</summary>{formatted_content}</details>"
        return formatted_content

    try:
        rows = extract_rows(triplets)
        if not rows:
            return ""
        columns = get_all_columns(rows)
        if not columns:
            return "没有找到有效的列"

        row_title = ""
        if (
            triplets
            and isinstance(triplets[0], list)
            and triplets[0]
            and isinstance(triplets[0][0], (tuple, list))
            and len(triplets[0][0]) > 0
        ):
            row_title = str(triplets[0][0][0]).strip()

        headers = [""] + columns
        markdown = f"| {' | '.join(headers)} |\n"
        markdown += f"|{'|'.join(['---'] * len(headers))}|\n"
        for row in rows:
            row_cells = [row_title]
            for col in columns:
                row_cells.append(format_cell_content(row.get(col, "")))
            markdown += f"| {' | '.join(row_cells)} |\n"
        return markdown
    except Exception as exc:
        return f"处理数据时出错: {exc}"


def get_llm_client_for_answer(model_name):
    # ko4csg_hci 内部函数：回答阶段根据模型名创建对应客户端或复用旧 LLM 配置。
    cfg = load_config()
    if model_name == cfg["qa_models"]["zhipuai"]["model_name"]:
        return OpenAI(api_key=cfg["qa_models"]["zhipuai"]["api_keys"], base_url=cfg["qa_models"]["zhipuai"]["base_url"])
    if model_name == cfg["qa_models"]["kimi"]["model_name"]:
        return OpenAI(api_key=cfg["qa_models"]["kimi"]["api_key"], base_url=cfg["qa_models"]["kimi"]["base_url"])
    return OpenAI(api_key=cfg["qa_models"]["qwen"]["api_key"], base_url=cfg["qa_models"]["qwen"]["base_url"])


def build_answer_chat_params(cfg, model_name, messages, is_thinking=False):
    if model_name == cfg["qa_models"]["zhipuai"]["model_name"]:
        provider_config = cfg["qa_models"]["zhipuai"]
    elif model_name == cfg["qa_models"]["kimi"]["model_name"]:
        provider_config = cfg["qa_models"]["kimi"]
    else:
        provider_config = cfg["qa_models"]["qwen"]
    params = {
        "model": model_name,
        "messages": messages,
        "temperature": provider_config.get("temperature", 0.1),
        "top_p": provider_config.get("top_p", 0.8),
        "max_tokens": provider_config.get("max_tokens", 4096),
        "stream": True,
    }
    extra_body = thinking_extra_body(model_name, is_thinking)
    if extra_body:
        params["extra_body"] = extra_body
    print(f"[LLM调用] model={model_name}, is_thinking={is_thinking}, extra_body={extra_body}")
    return params


def data_generator(triple_markdown, state, web, model_name, messages, streaming_flag, people_list_1=None, people_list_2=None, is_thinking=False):
    people_list_1 = people_list_1 or []
    people_list_2 = people_list_2 or []
    cfg = load_config()

    if streaming_flag:
        yield "data: zxl\n\n"

    sensitive_refusal = False
    try:
        answer_content = ""
        if model_name in {"spark", cfg["qa_models"]["spark"]["model_name"]}:
            from ..engine_dependencies.llm_clients import llm_config

            llm = llm_config()
            query = messages[-1]["content"]
            for delta in llm.spark(
                appid=cfg["qa_models"]["spark"]["appid"],
                api_key=cfg["qa_models"]["spark"]["api_keys"],
                api_secret=cfg["qa_models"]["spark"]["api_secret"],
                gpt_url=cfg["qa_models"]["spark"]["gpt_url"],
                domain=cfg["qa_models"]["spark"]["domain"],
                query=query,
            ):
                yield f"data: {delta}\n\n"
                answer_content += delta
        else:
            def create_stream(selected_model):
                client = get_llm_client_for_answer(selected_model)
                return client.chat.completions.create(
                    **build_answer_chat_params(cfg, selected_model, messages, is_thinking)
                )

            response, active_model = create_answer_stream_with_fallback(create_stream, model_name)

            if is_reasoning_model(active_model, is_thinking):
                is_answering = False
                yield "data: > **思考内容：**StReAmNeWlInEStReAmNeWlInE > \n\n"
                for chunk in response:
                    if not getattr(chunk, "choices", None):
                        continue
                    choice = chunk.choices[0]
                    if getattr(choice, "finish_reason", None) == "sensitive":
                        sensitive_refusal = True
                        answer_content += SENSITIVE_ERROR_MESSAGE
                        yield f"data: {SENSITIVE_ERROR_MESSAGE}\n\n"
                        break
                    delta = choice.delta
                    reasoning = getattr(delta, "reasoning_content", None)
                    content = getattr(delta, "content", None)
                    if reasoning:
                        text_delta = reasoning.replace("\n", "StReAmNeWlInE > ").replace(" ", "StReAmSpAcE")
                        yield f"data: {text_delta}\n\n"
                    # Providers may include reasoning and answer in the same delta.
                    if content:
                        if not is_answering:
                            is_answering = True
                            yield "data: StReAmNeWlInE --- StReAmNeWlInE\n\n"
                            yield "data: **开始回答：** StReAmNeWlInEStReAmNeWlInE \n\n"
                        text_delta = content.replace("\n", "StReAmNeWlInE").replace(" ", "StReAmSpAcE")
                        yield f"data: {text_delta}\n\n"
                        answer_content += content
                    time.sleep(0.01)
            else:
                for msg in response:
                    if not getattr(msg, "choices", None):
                        continue
                    choice = msg.choices[0]
                    if getattr(choice, "finish_reason", None) == "sensitive":
                        sensitive_refusal = True
                        answer_content += SENSITIVE_ERROR_MESSAGE
                        yield f"data: {SENSITIVE_ERROR_MESSAGE}\n\n"
                        break
                    delta = choice.delta
                    if delta.content:
                        text_delta = delta.content.replace("\n", "StReAmNeWlInE").replace(" ", "StReAmSpAcE")
                        yield f"data: {text_delta}\n\n"
                        answer_content += text_delta
                        time.sleep(0.01)

        if not answer_content:
            answer_content = EMPTY_MODEL_RESPONSE_MESSAGE
            yield f"data: {answer_content}\n\n"
        state.answer_content = answer_content
        if triple_markdown:
            yield "data: \n\nStReAmNeWlInEStReAmNeWlInE**以下是检索路径表格**\n\n\n"
            path_excel = triple_markdown.replace("\n", "StReAmNeWlInE").replace(" ", "StReAmSpAcE")
            yield f"data: \n\n<Lujingbiao>{path_excel}</Lujingbiao>\n\n\n\n"
        if len(people_list_2) > 1 or len(people_list_1) > 1:
            yield "data: \n\nStReAmNeWlInEStReAmNeWlInE**以下是多位同名人物信息**\n\n\n"
        if len(people_list_1) > 1:
            match = re.search(r"姓名:\s*([^,]+)", people_list_1[0])
            if match:
                yield f"data: \n\nStReAmNeWlInEStReAmNeWlInE **姓名:** {match.group(1).strip()}\n\n\n"
            for person in people_list_1:
                row_match = re.match(r"姓名:\s*([^,]+),\s*(.*)", person)
                if row_match:
                    yield f"data: \n\nStReAmNeWlInEStReAmNeWlInE - {row_match.group(2).strip()}\n\n"
        if len(people_list_2) > 1:
            match = re.search(r"姓名:\s*([^,]+)", people_list_2[0])
            if match:
                yield f"data: \n\nStReAmNeWlInEStReAmNeWlInE **姓名:** {match.group(1).strip()}\n\n\n"
            for person in people_list_2:
                row_match = re.match(r"姓名:\s*([^,]+),\s*(.*)", person)
                if row_match:
                    yield f"data: \n\nStReAmNeWlInEStReAmNeWlInE - {row_match.group(2).strip()}\n\n"
    except Exception as exc:
        traceback.print_exc()
        if getattr(exc, "code", None) == "data_inspection_failed":
            yield "data: 我们换个话题聊聊吧。\n\n"
        else:
            yield sse_error(USER_ERROR_MESSAGE)

    if sensitive_refusal:
        return
    if not web:
        yield "data: StReAmNeWlInEStReAmNeWlInE**您可以在输入栏左边选择开启联网搜索，以获取更多相关信息。**\n\n"
    yield "data: StReAmNeWlInEStReAmNeWlInE**如果您对回答结果不满意，您可以选择[上传文件]、或[上传表格录入]知识图谱、或在现有知识上[增设规则]，以改善回答效果。**\n\n"
    yield "data: StReAmNeWlInEStReAmNeWlInE**您可以点击查看[通用大模型]对该问题的回答结果。**\n\n"


def save_answer_history(qid, query, get_query_messages, state):
    # ko4csg_hci 内部函数：回答完成后同步内存历史和数据库历史。
    full_answer = state.answer_content.replace("StReAmNeWlInE", "\n").replace("StReAmSpAcE", " ")
    get_query_messages.append({"role": "assistant", "content": full_answer})
    qa_pair = [{"query": query, "answer": full_answer}]
    kdzn_history.add_or_update_user_qa(qid, get_query_messages[-2:])
    kdzn_history.remove_old_users()
    QA_history.add_or_update_user_qa(qid, qa_pair)
    QA_history.remove_old_users()
    qa_history = QA_history.get_user_qa_history(qid)
    update_sql_history(qid, qa_history)
    return qa_pair


def get_graph_kind(selected_main_scenario):
    if selected_main_scenario == "轨交诊断":
        return "kdzn"
    if selected_main_scenario in ("家谱问答", "家谱主题问答"):
        return "jiapu"
    return ""


def build_longest_path_query(label_with_id, max_hops=6):
    return f"""
        MATCH p=(root:`{label_with_id}`)-[*0..{max_hops}]->(t:`{label_with_id}` {{name: $tail}})
        WHERE ALL(n IN nodes(p) WHERE n.scene = $scene)
        RETURN p
        ORDER BY length(p) DESC
        LIMIT 1
    """.strip()


def extract_path_readable(path_obj):
    nodes = [node.get("name") or node.get("point") or "Unnamed" for node in getattr(path_obj, "nodes", [])]
    rels = [
        rel.get("name") or rel.get("edge_name") or getattr(rel, "type", "UNKNOWN")
        for rel in getattr(path_obj, "relationships", [])
    ]
    triples = [(nodes[index], rel, nodes[index + 1]) for index, rel in enumerate(rels) if index + 1 < len(nodes)]
    return {"nodes": nodes, "rels": rels, "triples": triples}


def run_longest_path_search(selected_main_scenario, label_with_id, scene, general_ranked_by_fo, general_over_by_fo):
    from ...common.neo4j_client import query_new_neo4j

    graph_kind = get_graph_kind(selected_main_scenario)
    cypher = build_longest_path_query(label_with_id, max_hops=10)
    paths_by_fo = {}

    for file_ontology, search_results in (general_ranked_by_fo or {}).items():
        over_flags = (general_over_by_fo or {}).get(file_ontology, [])
        for index, search_result in enumerate(search_results or []):
            if index >= len(over_flags) or not over_flags[index]:
                continue

            matched_entities = getattr(search_result, "matched_entities", None)
            if not isinstance(matched_entities, tuple) or len(matched_entities) < 2:
                continue

            score, tail_name = matched_entities[0], matched_entities[1]
            parameters = {"tail": tail_name, "scene": scene}
            pack = {"raw": [], "path": None}

            try:
                records = query_new_neo4j(cypher, parameters=parameters, kg=graph_kind)
                pack["raw"] = records
            except Exception as exc:
                print(f"[ko4csg_hci] longest path query failed: fo={file_ontology}, tail={tail_name}, error={exc}")
                records = []

            if records:
                try:
                    full_path = extract_path_readable(records[0]["p"])
                    nodes = full_path["nodes"]
                    target_idx = next(
                        (i for i, node_name in enumerate(nodes) if str(node_name).strip() == str(tail_name).strip()),
                        -1,
                    )
                    if target_idx >= 0:
                        pack["path"] = {"nodes": nodes[: target_idx + 1], "triples": full_path["triples"][:target_idx]}
                    else:
                        pack["path"] = {"nodes": nodes, "triples": full_path["triples"]}
                except Exception as exc:
                    print(f"[ko4csg_hci] longest path parse failed: fo={file_ontology}, tail={tail_name}, error={exc}")

            if not pack["path"]:
                try:
                    fallback = (
                        f"MATCH (n:`{label_with_id}`) "
                        "WHERE n.name = $tail AND n.scene = $scene RETURN n LIMIT 1"
                    )
                    node_records = query_new_neo4j(fallback, parameters=parameters, kg=graph_kind)
                    if node_records:
                        node_obj = node_records[0].get("n")
                        node_name = node_obj.get("name") or node_obj.get("point") or tail_name
                        pack = {"raw": node_records, "path": {"nodes": [node_name], "triples": []}}
                except Exception as exc:
                    print(f"[ko4csg_hci] longest path single-node fallback failed: {exc}")

            paths_by_fo.setdefault(file_ontology, {})[tail_name] = {
                "traceback": pack,
                "rule_paths": getattr(search_result, "paths", []) or [],
                "score": score,
            }

    return paths_by_fo


class RuleBuildHelper:
    def __init__(self, label, scene):
        self.label = label
        self.scene = scene

    def parse_arrow_path(self, path_str):
        if not path_str:
            return []
        parts = re.split(r"-\[(.*?)\]->", path_str)
        triples = []
        current_start = parts[0].strip()
        for index in range(1, len(parts), 2):
            if index + 1 >= len(parts):
                break
            rel_name = parts[index].strip()
            end_node = parts[index + 1].split("-[", 1)[0].strip()
            triples.append({"start": current_start, "rel": rel_name, "end": end_node})
            current_start = end_node
        return triples

    def generate_entry_rule(self, traceback_pack):
        path_data = (traceback_pack or {}).get("path")
        if not path_data:
            return ""
        triples = path_data.get("triples", [])
        if not triples:
            return f"MATCH (f:`{self.label}`) WHERE f.scene = '{self.scene}' RETURN f.name as RIName"
        rel_name = triples[-1][1]
        return (
            f"MATCH (f:`{self.label}`)-[:`{rel_name}`]->(RI:`{self.label}`) "
            f"WHERE RI.scene = '{self.scene}' RETURN RI.name as RIName"
        )

    def generate_path_rules(self, match_entity_name, rule_paths):
        generated_cyphers = set()
        clean_entity_name = str(match_entity_name or "").strip()
        for path_str in rule_paths or []:
            triples = self.parse_arrow_path(path_str)
            if not triples:
                continue

            def format_node(node_value):
                if str(node_value).strip() == clean_entity_name:
                    return f"(n:`{self.label}` {{name: \"{{entityname}}\"}})"
                return "()"

            cypher_chain = format_node(triples[0]["start"])
            for triple in triples:
                cypher_chain += f"-[:`{triple['rel']}`]->{format_node(triple['end'])}"
            generated_cyphers.add(f"MATCH p={cypher_chain} RETURN p")
        return list(generated_cyphers)


def build_rule_candidates(selected_main_scenario, label_with_id, scene, general_ranked_by_fo, general_over_by_fo):
    helper = RuleBuildHelper(label_with_id, scene)
    full_results_by_fo = run_longest_path_search(
        selected_main_scenario,
        label_with_id,
        scene,
        general_ranked_by_fo,
        general_over_by_fo,
    )
    rule_candidates = []

    for file_ontology, entities_map in full_results_by_fo.items():
        for tail_name, data in (entities_map or {}).items():
            try:
                entry_cypher = helper.generate_entry_rule(data.get("traceback"))
                generated_rule_paths = helper.generate_path_rules(tail_name, data.get("rule_paths"))
                if entry_cypher:
                    rule_candidates.append(
                        {
                            "entity": tail_name,
                            "file_ontology": file_ontology,
                            "getIn4simi": entry_cypher,
                            "rule_path": generated_rule_paths,
                        }
                    )
            except Exception as exc:
                print(f"[ko4csg_hci] build rule candidate failed: fo={file_ontology}, tail={tail_name}, error={exc}")

    return rule_candidates


def parse_json_list_from_text(text):
    if not text:
        return []
    try:
        match = re.search(r"\[[\s\S]*\]", text)
        return json.loads(match.group(0) if match else text)
    except Exception as exc:
        print(f"[ko4csg_hci] parse rule-name JSON failed: {exc}; raw={str(text)[:300]}")
        return []


def generate_generalized_rule_names(qa_pair, rule_candidates):
    from ..engine_dependencies.llm_clients import call_qwen_messages

    if not rule_candidates:
        return []

    prompt = f"""
你是知识图谱业务规则架构师。请根据问答上下文，为候选规则生成清晰、可复用、业务化的规则名称。
要求：
1. 只返回 JSON 数组，不要 Markdown，不要解释。
2. 保留每条候选规则的 getIn4simi 和 rule_path，不要改写。
3. 输出字段为 rulename、getIn4simi、rule_path。
4. rulename 不要直接使用具体实体名，尽量泛化为业务对象。

问答上下文：
{json.dumps(qa_pair, ensure_ascii=False, default=str)}

候选规则：
{json.dumps(rule_candidates, ensure_ascii=False, default=str)}
""".strip()
    try:
        response = call_qwen_messages(
            [{"role": "user", "content": prompt}],
            model_name="qwen2.5",
        )
    except Exception as exc:
        print(f"[ko4csg_hci] rule-name LLM failed: {exc}")
        return []
    rules = parse_json_list_from_text(response)
    normalized_rules = []
    for item in rules:
        if not isinstance(item, dict):
            continue
        rule_name = item.get("rulename") or item.get("rule_name")
        get_in_4_simi = item.get("getIn4simi")
        rule_path = item.get("rule_path")
        if rule_name and get_in_4_simi and rule_path:
            normalized_rules.append({"rulename": rule_name, "getIn4simi": get_in_4_simi, "rule_path": rule_path})
    return normalized_rules


def insert_rule_data(connection, data_list, label_with_id, scene, selected_main_scenario):
    from ..engine_dependencies.rule_vector_builder import (
        build_rule_entity_vector_store,
    )

    if not connection:
        print("[ko4csg_hci] skip rule insert: database connection unavailable")
        return

    rule_name = data_list[2]
    rule_paths = data_list[3]
    get_in_4_simi = data_list[4]
    rule_path_human = data_list[5]
    get_in_4_simi_human = data_list[6]

    if isinstance(rule_paths, str):
        rule_paths = [rule_paths]
    if not isinstance(rule_paths, list):
        print("[ko4csg_hci] skip rule insert: rule_path is not list/string")
        return

    for single_path in rule_paths:
        try:
            with connection.cursor() as cursor:
                cursor.execute(
                    """
                    INSERT INTO ko_kdzn_rule_construct
                    (theme_name, theme_label, scene, rulename, rulepath, getin4simi, rulepath_human, getin4simi_human)
                    VALUES (%s, %s, %s, %s, %s, %s, %s, %s)
                    """,
                    (
                        selected_main_scenario,
                        label_with_id,
                        scene,
                        rule_name,
                        single_path,
                        get_in_4_simi,
                        rule_path_human,
                        get_in_4_simi_human,
                    ),
                )
                new_rid = cursor.lastrowid
                connection.commit()

                if new_rid and selected_main_scenario != "家谱问答":
                    build_rule_entity_vector_store(
                        {
                            "rid": new_rid,
                            "theme_name": selected_main_scenario,
                            "theme_label": label_with_id,
                            "getin4simi": get_in_4_simi,
                        }
                    )
        except Exception as exc:
            try:
                connection.rollback()
            except Exception:
                pass
            print(f"[ko4csg_hci] insert/generated rule vector failed: rule={rule_name}, error={exc}")


def generate_and_save_rules_after_answer(
    selected_main_scenario,
    selected_main_scenario_label_with_id,
    file_ontology_list,
    general_ranked_by_fo,
    general_over_by_fo,
    qa_pair,
):
    # ko4csg_hci 内部函数：问答结束后触发规则泛化、规则命名、入库和向量生成。
    if not file_ontology_list or not general_ranked_by_fo:
        return

    scene = file_ontology_list[0]
    label_with_id = selected_main_scenario_label_with_id
    if selected_main_scenario == "家谱问答":
        label_with_id = "huaputong"

    rule_candidates = build_rule_candidates(
        selected_main_scenario,
        label_with_id,
        scene,
        general_ranked_by_fo,
        general_over_by_fo,
    )
    if not rule_candidates:
        print("[ko4csg_hci] no rule candidates generated")
        return

    final_rules = generate_generalized_rule_names(qa_pair, rule_candidates)
    if not final_rules:
        print("[ko4csg_hci] no generalized rules returned by LLM")
        return

    db_connection = connect_to_db()
    try:
        for rule_item in final_rules:
            current_rule_data = [
                selected_main_scenario,
                scene,
                rule_item["rulename"],
                rule_item["rule_path"],
                rule_item["getIn4simi"],
                rule_item["rulename"],
                "",
                "",
            ]
            insert_rule_data(db_connection, current_rule_data, label_with_id, scene, selected_main_scenario)
    finally:
        if db_connection:
            db_connection.close()


def get_kdzn_engine():
    # ko4csg_hci 内部函数：加载本接口专属的 kdzn 图谱问答引擎。
    from ..engine_dependencies.kdzn_graph_qa_engine import kdzn_qa

    return kdzn_qa()


async def handle_ko4csg_hci(request):
    # ko4csg_hci 接口主编排：只服务 kdzn_hciqa.vue 的 /ko4csg_hci。
    csg_res = Result()
    try:
        query_data = await request.json()
    except Exception as exc:
        csg_res.status = 400
        csg_res.errorMessage = f"请求体 JSON 解析失败: {exc}"
        return csg_res

    qid = query_data.get("qid")
    user_id = query_data.get("userId") or ""
    query = query_data.get("query")
    model_choose = query_data.get("model_choose", "Auto")
    scene_choose = query_data.get("scene_choose", "轨交诊断")
    web = query_data.get("web", False)
    bigbase = query_data.get("bigbase", False)

    if not query or not qid:
        csg_res.status = 400
        csg_res.errorMessage = "输入问题和 qid 不能为空"
        return csg_res

    koqatheme_label = han2pinyin_concat(scene_choose)
    koqatheme_label_with_id = koqatheme_label + f"_{user_id}"
    need_judge_diff = model_choose == "Auto"

    q_history = kdzn_history.get_user_qa_history(qid)
    qa_pair_history = QA_history.get_user_qa_history(qid)
    state = SimpleNamespace(reasoning_content="", answer_content="", is_answering=False)
    event_queue = queue.Queue()

    history_qa, error_response = load_history_qa(qid)
    if error_response is not None:
        return error_response

    def worker(selected_main_scenario, selected_main_scenario_label_with_id):
        ans_over = False
        file_ontology_list = []
        get_query_messages = []
        general_ranked_by_fo = {}
        general_over_by_fo = {}
        qa_pair = None

        try:
            kdzn = get_kdzn_engine()
            (
                file_ontology_list,
                get_query_messages,
                _get_path,
                triple_excel,
                _unused,
                difficulty,
                streaming_flag,
                q,
                people_list_1,
                people_list_2,
                general_ranked_by_fo,
                general_over_by_fo,
            ) = kdzn.csg_port_stream(
                qa_pair_history,
                selected_main_scenario_label_with_id,
                user_id,
                history_qa,
                event_queue,
                query,
                scene_choose,
                web,
                bigbase,
                q_history,
                need_judge_diff=need_judge_diff,
                session_id=qid,
            )

            model_llm = get_model(model_choose, difficulty)
            is_thinking = is_thinking_selection(model_choose, difficulty)
            if scene_choose == "家谱问答":
                triple_markdown = jiapu_to_excel_markdown(triple_excel)
            else:
                triple_markdown = triplets_to_markdown_table(triple_excel)

            q.put(sse_message("完成"))
            q.put(sse_message("正在通过大模型分析，请稍后"))

            for event in data_generator(
                triple_markdown,
                state,
                web,
                model_llm,
                get_query_messages,
                streaming_flag,
                people_list_1,
                people_list_2,
                is_thinking=is_thinking,
            ):
                q.put(event)
            ans_over = True
        except Exception as exc:
            traceback.print_exc()
            print(f"[ko4csg_hci] worker error: {exc}")
            event_queue.put(sse_error(USER_ERROR_MESSAGE))
        finally:
            event_queue.put(None)

        if qid and ans_over:
            try:
                qa_pair = save_answer_history(qid, query, get_query_messages, state)
            except Exception as exc:
                print(f"[ko4csg_hci] save history failed: {exc}")

            if qa_pair is not None:
                try:
                    generate_and_save_rules_after_answer(
                        selected_main_scenario,
                        selected_main_scenario_label_with_id,
                        file_ontology_list,
                        general_ranked_by_fo,
                        general_over_by_fo,
                        qa_pair,
                    )
                except Exception as exc:
                    print(f"[ko4csg_hci] generate/save rules failed: {exc}")

    threading.Thread(target=worker, args=(scene_choose, koqatheme_label_with_id), daemon=True).start()
    return stream_response(event_queue, timeout=80)
