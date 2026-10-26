import hashlib
import json
import re
from collections import defaultdict
from openai import OpenAI
import pymysql
import yaml
from tqdm import tqdm
from vue_api.common.neo4j_client import (
    create_neo4j_driver,
    query_new_neo4j,
)
from vue_api.common.paths import CONFIG_PATH

with CONFIG_PATH.open(encoding="utf-8") as f:
    cfg = yaml.safe_load(f)

__all__ = [
    "insert_records_to_graph",
    "insert_records_to_graph_jiapu",
    "insert_triples_to_graph",
    "query_new_neo4j",
]



def build_chat_params(provider_config, *, model, messages):
    return {
        "model": model,
        "messages": messages,
        "temperature": provider_config.get("temperature", 0.0),
        "top_p": provider_config.get("top_p", 0.8),
        "max_tokens": provider_config.get("max_tokens", 4096),
        "stream": False,
    }



def qwen(mess):
    _qwen2 = OpenAI(
        api_key=cfg["small_models"]["qwen"]["api_key"],  # 如果您没有配置环境变量，请在此处用您的API Key进行替换
        base_url=cfg["small_models"]["qwen"]["base_url"],  # 填写DashScope SDK的base_url
    )
    quest_model = cfg["small_models"]["qwen"]["qwen2.5_model_name"]
    try:
        completion = _qwen2.chat.completions.create(
            **build_chat_params(cfg["small_models"]["qwen"], model=quest_model, messages=mess)
        )
        # print(f"\033[96mQwen2使用token量：{completion.usage} \033[0m")
        return completion.choices[0].message.content
    except Exception as e:
        if getattr(e, "code", None) == 'data_inspection_failed':
            return "我们换个话题聊聊吧。"
        print(f"[graph_construct] Qwen API 调用失败: {repr(e)}")
        return None



def connect_to_db():
    try:
        connection = pymysql.connect(
            host=cfg["KO_database"]["host"],  # 数据库主机
            user=cfg["KO_database"]["user"],  # 数据库用户名
            password=cfg["KO_database"]["password"],  # 数据库密码
            database=cfg["KO_database"]["database"],
            charset=cfg["KO_database"]["charset"]
        )
        return connection
    except pymysql.MySQLError as err:
        print(f"Error: {err}")
        return None


def create_driver_by_kg(kg=''):
    return create_neo4j_driver(kg)


def create_driver_for_graph_insert(selectedMainScenario, label):
    if selectedMainScenario == '轨交诊断':
        return create_neo4j_driver("kdzn"), "kedazhineng"
    if selectedMainScenario == '家谱问答':
        return create_neo4j_driver("jiapu"), "jiapuwenda"
    return create_neo4j_driver(""), label


def graph_norm(value):
    text = str(value).strip() if value is not None else ""
    return text if text not in ("", "None", "null", "/") else ""


def ensure_nodekey_constraint(session, label_name: str):
    safe = re.sub(r"\W", "_", label_name)
    cname = f"{safe}_nodekey"
    try:
        session.run(
            f"CREATE CONSTRAINT {cname} IF NOT EXISTS "
            f"FOR (n:`{label_name}`) "
            f"REQUIRE n.node_key IS UNIQUE"
        )
    except Exception:
        try:
            session.run(
                f"CREATE CONSTRAINT ON (n:`{label_name}`) "
                f"ASSERT n.node_key IS UNIQUE"
            )
        except Exception as e_old:
            msg = str(e_old).lower()
            if "already" in msg and "exist" in msg:
                return
            print(f"[graph_construct] 创建 node_key 约束失败: {e_old}")


def resolve_triple_column_indices(header):
    idx_head, idx_rel, idx_tail = 0, 1, 2
    if header == ['根节点', '类型', '头实体', '关系', '尾实体']:
        print("检测到5列数据格式，将忽略'根节点'和'类型'，仅提取后三列。")
        idx_head, idx_rel, idx_tail = 2, 3, 4
    return idx_head, idx_rel, idx_tail


def build_triple_adjacency(rows, idx_head, idx_rel, idx_tail):
    adj_list = defaultdict(list)
    all_heads = set()
    all_tails = set()
    valid_rows_count = 0

    for row in rows:
        if len(row) <= max(idx_head, idx_rel, idx_tail):
            continue
        head = graph_norm(row[idx_head])
        rel = graph_norm(row[idx_rel])
        tail = graph_norm(row[idx_tail])
        if not head or not tail or not rel:
            continue
        adj_list[head].append((rel, tail))
        all_heads.add(head)
        all_tails.add(tail)
        valid_rows_count += 1

    return adj_list, all_heads, all_tails, valid_rows_count


def resolve_triple_roots(all_heads, all_tails):
    roots = list(all_heads - all_tails)
    if not roots and all_heads:
        print("未检测到明显的根节点（可能是循环图），将所有头实体视为入口。")
        roots = list(all_heads)
    return roots


def build_path_key_payloads(scene, graph_name, adj_list, roots):
    grouped_payloads = defaultdict(list)
    names_collected = set()
    processed_edges = set()
    max_depth_found = 0
    max_depth_path_end = None
    stack = [(root, f"{scene}_{root}", {root}, 0) for root in roots]

    while stack:
        current_node_name, current_node_key, path_visited, depth = stack.pop()
        names_collected.add(current_node_name)

        if depth > max_depth_found:
            max_depth_found = depth
            max_depth_path_end = current_node_key

        for rel, child_name in adj_list.get(current_node_name, []):
            if child_name in path_visited:
                continue

            child_key = f"{current_node_key}_{child_name}"
            edge_signature = (current_node_key, rel, child_key)
            if edge_signature in processed_edges:
                continue
            processed_edges.add(edge_signature)

            safe_rel = rel.replace("`", "").replace("'", "")
            grouped_payloads[safe_rel].append({
                "h_key": current_node_key,
                "h_name": current_node_name,
                "t_key": child_key,
                "t_name": child_name,
                "h_depth": depth,
                "t_depth": depth + 1,
                "scene": scene,
                "graph_name": graph_name,
            })
            stack.append((child_name, child_key, path_visited | {child_name}, depth + 1))

    print(f"数据处理完成：最大跳数(max hops) = {max_depth_found}, end={max_depth_path_end}")
    return grouped_payloads, names_collected


def write_triple_payloads(session, label, grouped_payloads, batch_size):
    label_literal = f"`{label}`"
    cypher_triple = (
        f"UNWIND $rows AS row\n"
        f"MERGE (h:{label_literal} {{ node_key: row.h_key }})\n"
        f"  ON CREATE SET h.name = row.h_name, h.scene = row.scene, h.graph_name = row.graph_name\n"
        f"MERGE (t:{label_literal} {{ node_key: row.t_key }})\n"
        f"  ON CREATE SET t.name = row.t_name, t.scene = row.scene, t.graph_name = row.graph_name\n"
        f"MERGE (h)-[r:`__REL__`]->(t)\n"
        f"  ON CREATE SET r.graph_name = row.graph_name\n"
        f"RETURN count(r) AS cnt"
    )
    total_rels_created = 0
    for rel_type, items in grouped_payloads.items():
        query = cypher_triple.replace("__REL__", rel_type)
        for index in tqdm(range(0, len(items), batch_size), desc=f"Import Path [{rel_type}]"):
            batch = items[index: index + batch_size]
            try:
                result = session.execute_write(lambda tx: tx.run(query, rows=batch).single())
                if result:
                    total_rels_created += result["cnt"]
            except Exception as exc:
                print(f"写入失败 [{rel_type}]: {exc}")
    return total_rels_created


def is_empty_graph_data(json_data):
    return not json_data


def safe_property_key(header_text: str, idx: int) -> str:
    text = "" if header_text is None else str(header_text)
    text = re.sub(r"[^\w]", "_", text, flags=re.UNICODE)
    text = re.sub(r"_+", "_", text).strip("_")
    if not text or not text[0].isalpha():
        text = f"p_{idx}" if not text else f"p_{idx}_{text}"
    return text


def build_table_merge_keys(scene, col_idx: int, row, headers, telem_cls, telem_pt):
    keys = {"name": graph_norm(row[col_idx])}
    if col_idx == 0:
        keys["scene"] = scene
    if col_idx >= 2 and telem_cls:
        keys["class"] = telem_cls
    if col_idx >= 3 and telem_pt:
        keys["point"] = telem_pt
    if col_idx == 2 and len(row) > 1:
        prev_val = graph_norm(row[1])
        if prev_val:
            keys[safe_property_key(headers[1] if 1 < len(headers) else "col_1", 1)] = prev_val
    if col_idx >= 3:
        for index in range(3, min(col_idx, len(headers))):
            val = graph_norm(row[index]) if index < len(row) else ""
            if val:
                keys[safe_property_key(headers[index] if index < len(headers) else f"col_{index}", index)] = val
    return keys


def to_node_key(key_dict: dict) -> str:
    payload = json.dumps(key_dict, sort_keys=True, ensure_ascii=False)
    return hashlib.md5(payload.encode("utf-8")).hexdigest()


def build_table_on_create_map(scene, col_idx: int, row, headers, telem_cls, telem_pt, root_node):
    col_name = str(headers[col_idx]) if col_idx < len(headers) else f"col_{col_idx}"
    on_map = {
        "scene": scene,
        "type": col_name,
        "name": graph_norm(row[col_idx]),
    }
    if col_idx > 0 and root_node:
        on_map["root_node"] = root_node
    if col_idx >= 2 and telem_cls:
        on_map["class"] = telem_cls
    if col_idx >= 3 and telem_pt:
        on_map["point"] = telem_pt
    if col_idx == 2 and len(row) > 1:
        prev_val = graph_norm(row[1])
        if prev_val:
            on_map[safe_property_key(headers[1] if 1 < len(headers) else "col_1", 1)] = prev_val
    if col_idx >= 3:
        for index in range(3, min(col_idx, len(headers))):
            val = graph_norm(row[index]) if index < len(row) else ""
            if val:
                on_map[safe_property_key(headers[index] if index < len(headers) else f"col_{index}", index)] = val
    return on_map


def build_table_graph_payloads(scene, graph_name, headers, data_rows):
    rows_payload = []
    names_seq = []

    for row in data_rows:
        if len(row) < 2:
            continue
        root_node = graph_norm(row[0]) if len(row) > 0 else ""
        telem_cls = graph_norm(row[2]) if len(row) > 2 else ""
        telem_pt = graph_norm(row[3]) if len(row) > 3 else ""

        for a_col in range(len(row) - 1):
            b_col = a_col + 1
            a_name = graph_norm(row[a_col])
            b_name = graph_norm(row[b_col])
            if not a_name or not b_name:
                continue

            names_seq.extend([a_name, b_name])
            a_keys_dict = build_table_merge_keys(scene, a_col, row, headers, telem_cls, telem_pt)
            b_keys_dict = build_table_merge_keys(scene, b_col, row, headers, telem_cls, telem_pt)
            if a_keys_dict == b_keys_dict:
                continue

            rel_type = str(headers[b_col]) if b_col < len(headers) else f"COL_{b_col}"
            rows_payload.append({
                "a_key": to_node_key(a_keys_dict),
                "b_key": to_node_key(b_keys_dict),
                "a_on": build_table_on_create_map(scene, a_col, row, headers, telem_cls, telem_pt, root_node),
                "b_on": build_table_on_create_map(scene, b_col, row, headers, telem_cls, telem_pt, root_node),
                "rel_type": rel_type.replace("`", "´"),
                "graph_name": graph_name,
            })

    names_list = []
    seen = set()
    for name in names_seq:
        if name and name not in seen:
            seen.add(name)
            names_list.append(name)
    return rows_payload, names_list


def group_payloads_by_relation(rows_payload):
    grouped = defaultdict(list)
    for row in rows_payload:
        grouped[row["rel_type"]].append(row)
    return grouped


def write_table_payloads(session, label, grouped_payloads, batch_size):
    label_literal = f"`{label}`"
    cypher_tmpl = (
        f"UNWIND $rows AS row\n"
        f"MERGE (a:{label_literal} {{ node_key: row.a_key }})\n"
        f"  ON CREATE SET a += row.a_on\n"
        f"MERGE (b:{label_literal} {{ node_key: row.b_key }})\n"
        f"  ON CREATE SET b += row.b_on\n"
        f"MERGE (a)-[r:`__REL__`]->(b)\n"
        f"  ON CREATE SET r.graph_name = row.graph_name\n"
        f"RETURN count(r) AS cnt"
    )
    inserted = 0
    for rel_type, rows in grouped_payloads.items():
        cypher = cypher_tmpl.replace("__REL__", rel_type)
        for index in tqdm(range(0, len(rows), batch_size), desc=f"MERGE [{rel_type}]"):
            batch = rows[index:index + batch_size]
            result = session.execute_write(lambda tx: tx.run(cypher, rows=batch).single())
            inserted += result["cnt"]
    return inserted


def ensure_jiapu_indexes(session, label_name: str):
    try:
        session.run(
            f"CREATE CONSTRAINT {label_name}_person_key IF NOT EXISTS "
            f"FOR (n:`{label_name}`:`人物`) REQUIRE (n.id, n.scene, n.graph_name) IS UNIQUE"
        )
        return
    except Exception:
        pass
    try:
        session.run(
            f"CREATE INDEX {label_name}_person_id_scene_g IF NOT EXISTS "
            f"FOR (n:`{label_name}`:`人物`) ON (n.id, n.scene, n.graph_name)"
        )
        return
    except Exception:
        pass
    for prop in ("id", "scene", "graph_name"):
        try:
            session.run(
                f"CREATE INDEX {label_name}_person_{prop} IF NOT EXISTS "
                f"FOR (n:`{label_name}`:`人物`) ON (n.{prop})"
            )
        except Exception:
            continue


def resolve_header_index(headers, column, default):
    try:
        return headers.index(column)
    except ValueError:
        return default


def resolve_jiapu_columns(headers):
    return {
        "id": resolve_header_index(headers, "编号", 0),
        "father": resolve_header_index(headers, "父亲编号", 1),
        "spouse": resolve_header_index(headers, "配偶编号", 2),
        "name": resolve_header_index(headers, "姓名", 3),
        "gender": resolve_header_index(headers, "性别", 4),
        "bio": resolve_header_index(headers, "简介", 5),
        "zibei": resolve_header_index(headers, "字辈", -1),
        "shidai": resolve_header_index(headers, "世代", -1),
    }


def build_jiapu_generation_map(rows, columns):
    i_zibei = columns["zibei"]
    i_shidai = columns["shidai"]
    if i_zibei < 0 or i_shidai < 0:
        print("未在表头中检测到“字辈”或“世代”列，跳过字辈映射。")
        return {}

    shidai2zibei = {}
    for row in rows:
        if i_shidai >= len(row) or i_zibei >= len(row):
            continue
        shidai = str(row[i_shidai]).strip()
        zibei = str(row[i_zibei]).strip()
        if not shidai or not zibei:
            continue
        zibei_list = shidai2zibei.setdefault(shidai, [])
        if zibei not in zibei_list:
            zibei_list.append(zibei)
    print(f"字辈映射(世代->字辈列表)：{shidai2zibei}")
    return shidai2zibei


def build_jiapu_id_name_map(rows, columns):
    id2name = {}
    for row in rows:
        pid = graph_norm(row[columns["id"]]) if columns["id"] < len(row) else ""
        name = graph_norm(row[columns["name"]]) if columns["name"] < len(row) else ""
        if pid and name and pid != "编号" and name != "姓名":
            id2name[pid] = name
    return id2name


def build_jiapu_payloads(scene, graph_name, rows, columns, id2name):
    persons = []
    fathers = {"儿子": [], "女儿": [], "孩子": []}
    spouses = []
    all_ids = set()

    for row in rows:
        pid = graph_norm(row[columns["id"]]) if columns["id"] < len(row) else ""
        fid = graph_norm(row[columns["father"]]) if columns["father"] < len(row) else ""
        sid = graph_norm(row[columns["spouse"]]) if columns["spouse"] < len(row) else ""
        pname = graph_norm(row[columns["name"]]) if columns["name"] < len(row) else ""
        gender = graph_norm(row[columns["gender"]]) if columns["gender"] < len(row) else ""
        bio = graph_norm(row[columns["bio"]]) if columns["bio"] < len(row) else ""
        zibei = graph_norm(row[columns["zibei"]]) if columns["zibei"] >= 0 and columns["zibei"] < len(row) else ""
        generation = graph_norm(row[columns["shidai"]]) if columns["shidai"] >= 0 and columns["shidai"] < len(row) else ""

        if not pid or not pname or pid == "编号" or pname == "姓名":
            continue

        persons.append({
            "id": pid, "scene": scene, "g": graph_name,
            "name": pname, "gender": gender, "bio": bio,
            "url": f"ko-qa-huapu-{pid}",
            "generation_poem": zibei,
            "generation": generation,
        })

        if fid:
            rel = "儿子" if gender == "男" else ("女儿" if gender == "女" else "孩子")
            fathers[rel].append({
                "fid": fid, "fname": id2name.get(fid, ""), "furl": f"ko-qa-huapu-{fid}",
                "pid": pid, "scene": scene, "g": graph_name,
            })
        if sid:
            spouses.append({
                "sid": sid, "sname": id2name.get(sid, ""), "surl": f"ko-qa-huapu-{sid}",
                "pid": pid, "scene": scene, "g": graph_name,
            })
        all_ids.add(pid)
        if fid:
            all_ids.add(fid)
        if sid:
            all_ids.add(sid)

    return persons, fathers, spouses, all_ids


def cypher_jiapu_templates(label):
    label_literal = f"`{label}`"
    persons = (
        f"UNWIND $rows AS row\n"
        f"MERGE (p:{label_literal}:`人物` {{ id: row.id, scene: row.scene, graph_name: row.g }})\n"
        f"  ON CREATE SET p.name=row.name, p.url=row.url, p.gender=row.gender, p.des=row.bio,\n"
        f"                p.generation=row.generation, p.generation_poem=row.generation_poem\n"
        f"  ON MATCH  SET p.name=row.name, p.url=row.url,\n"
        f"               p.gender = CASE WHEN row.gender <> '' THEN row.gender ELSE p.gender END,\n"
        f"               p.des    = CASE WHEN row.bio    <> '' THEN row.bio    ELSE p.des    END,\n"
        f"               p.generation = CASE WHEN row.generation <> '' THEN row.generation ELSE p.generation END,\n"
        f"               p.generation_poem  = CASE WHEN row.generation_poem  <> '' THEN row.generation_poem  ELSE p.generation_poem  END\n"
        f"RETURN count(p) AS cnt"
    )
    father_node = (
        f"UNWIND $rows AS row\n"
        f"MERGE (f:{label_literal}:`人物` {{ id: row.fid, scene: row.scene, graph_name: row.g }})\n"
        f"  ON CREATE SET f.name = COALESCE(row.fname, ''), f.url = row.furl\n"
        f"  ON MATCH  SET f.url  = row.furl\n"
        f"RETURN count(f) AS cnt"
    )
    spouse_node = (
        f"UNWIND $rows AS row\n"
        f"MERGE (s:{label_literal}:`人物` {{ id: row.sid, scene: row.scene, graph_name: row.g }})\n"
        f"  ON CREATE SET s.name = COALESCE(row.sname, ''), s.url = row.surl\n"
        f"  ON MATCH  SET s.url  = row.surl\n"
        f"RETURN count(s) AS cnt"
    )
    spouse_rel = (
        f"UNWIND $rows AS row\n"
        f"MATCH (p:{label_literal}:`人物` {{ id: row.pid, scene: row.scene, graph_name: row.g }})\n"
        f"MATCH (s:{label_literal}:`人物` {{ id: row.sid, scene: row.scene, graph_name: row.g }})\n"
        f"MERGE (p)-[r:`妻子`]->(s)\n"
        f"  ON CREATE SET r.graph_name = row.g\n"
        f"RETURN count(r) AS cnt"
    )
    return persons, father_node, spouse_node, spouse_rel


def cypher_jiapu_father_rel(label, rel_type):
    label_literal = f"`{label}`"
    rel_escaped = rel_type.replace("`", "´")
    return (
        f"UNWIND $rows AS row\n"
        f"MATCH (f:{label_literal}:`人物` {{ id: row.fid, scene: row.scene, graph_name: row.g }})\n"
        f"MATCH (c:{label_literal}:`人物` {{ id: row.pid, scene: row.scene, graph_name: row.g }})\n"
        f"MERGE (f)-[r:`{rel_escaped}`]->(c)\n"
        f"  ON CREATE SET r.graph_name = row.g\n"
        f"RETURN count(r) AS cnt"
    )


def write_jiapu_payloads(session, label, persons, fathers, spouses, batch_size):
    cypher_persons, cypher_father_node, cypher_spouse_node, cypher_spouse_rel = cypher_jiapu_templates(label)
    total_nodes, total_rels = 0, 0

    for index in tqdm(range(0, len(persons), batch_size), desc="MERGE persons"):
        batch = persons[index:index + batch_size]
        total_nodes += session.execute_write(lambda tx: tx.run(cypher_persons, rows=batch).single()["cnt"])

    father_nodes = []
    for rows_rel in fathers.values():
        father_nodes.extend(rows_rel)
    for index in tqdm(range(0, len(father_nodes), batch_size), desc="MERGE father nodes"):
        batch = father_nodes[index:index + batch_size]
        session.execute_write(lambda tx: tx.run(cypher_father_node, rows=batch).consume())

    for rel, rows_rel in fathers.items():
        if not rows_rel:
            continue
        cypher_rel = cypher_jiapu_father_rel(label, rel)
        for index in tqdm(range(0, len(rows_rel), batch_size), desc=f"MERGE rel {rel}"):
            batch = rows_rel[index:index + batch_size]
            total_rels += session.execute_write(lambda tx: tx.run(cypher_rel, rows=batch).single()["cnt"])

    if spouses:
        for index in tqdm(range(0, len(spouses), batch_size), desc="MERGE spouse nodes"):
            batch = spouses[index:index + batch_size]
            session.execute_write(lambda tx: tx.run(cypher_spouse_node, rows=batch).consume())
        for index in tqdm(range(0, len(spouses), batch_size), desc="MERGE rel 妻子"):
            batch = spouses[index:index + batch_size]
            total_rels += session.execute_write(lambda tx: tx.run(cypher_spouse_rel, rows=batch).single()["cnt"])

    return total_nodes, total_rels


def build_jiapu_names_list(all_ids, id2name):
    names_list = []
    seen = set()
    for item_id in all_ids:
        name = id2name.get(item_id, "").strip()
        if name and name not in seen:
            seen.add(name)
            names_list.append(name)
    return names_list



def insert_records_to_graph_jiapu(scene, koqatheme_label_with_ID, selectedMainScenario,
                                  json_data, graph_name, scene_description, selectedMainScenario_description,
                                  batch_size=2000):
    print(scene, koqatheme_label_with_ID, selectedMainScenario, graph_name, scene_description,
          selectedMainScenario_description)
    koqatheme_label_with_ID = "huaputong"
    is_empty = is_empty_graph_data(json_data)
    driver = create_neo4j_driver("jiapu")

    # 如果是空数据，只创建必要的索引结构
    if is_empty:
        print("检测到空数据，只创建索引结构")
        try:
            with driver.session() as session:
                ensure_jiapu_indexes(session, koqatheme_label_with_ID)
                print(f"[完成] 空数据场景创建成功（图谱={graph_name}，场景={scene}，标签={koqatheme_label_with_ID}）。")
        finally:
            driver.close()
        return True, []

    # 原始的数据处理逻辑（非空数据）
    if len(json_data) < 2:
        print("json_data 没有数据行")
        return True, []

    # 可选：保持你原来的 prompt 逻辑
    try:
        flag = get_prompt(selectedMainScenario, scene_description, scene, selectedMainScenario_description)
        print(f"场景{selectedMainScenario}下的prompt生成完成！" if flag else "prompt生成出错！")
    except Exception:
        pass

    headers = [str(h).strip() for h in json_data[0]]
    rows = [r for r in json_data[1:] if any(str(c).strip() for c in r)]
    columns = resolve_jiapu_columns(headers)
    build_jiapu_generation_map(rows, columns)

    # id -> name（先扫一遍，用于给父/配偶补名）
    id2name = build_jiapu_id_name_map(rows, columns)

    # ----------- 组装批量 payload -----------
    persons, fathers, spouses, all_ids = build_jiapu_payloads(scene, graph_name, rows, columns, id2name)

    if not persons:
        print("没有有效人物，只创建索引结构")
        # 即使没有有效人物，也确保索引存在
        try:
            with driver.session() as session:
                ensure_jiapu_indexes(session, koqatheme_label_with_ID)
                print(f"[完成] 空数据结构创建成功（图谱={graph_name}，场景={scene}，标签={koqatheme_label_with_ID}）。")
        finally:
            driver.close()
        return True, []

    # ----------- 执行批量写入 -----------
    try:
        with driver.session() as session:
            ensure_jiapu_indexes(session, koqatheme_label_with_ID)
            total_nodes, total_rels = write_jiapu_payloads(
                session, koqatheme_label_with_ID, persons, fathers, spouses, batch_size
            )
    finally:
        driver.close()

    names_list = build_jiapu_names_list(all_ids, id2name)
    print(
        f"[完成] 写入人物 {total_nodes} 个，关系 {total_rels} 条（图谱={graph_name}，场景={scene}，标签={koqatheme_label_with_ID}）。")
    return True, names_list



def insert_triples_to_graph(
        scene, koqatheme_label_with_ID, selectedMainScenario,
        json_data, graph_name, scene_description, selectedMainScenario_description,
        batch_size=2000
):
    """
    处理标准三元组数据：['头实体', '关系', '尾实体']
    逻辑改动：
    1. 不再逐行生成 Key，而是先构建内存图结构。
    2. 采用 DFS 深度优先遍历，将父节点的 Key 传递给子节点。
    3. 子节点的 Node_Key = f"{父节点Key}_{子节点名}"，实现全路径唯一标识。
    """

    # ---------------- 基础检查与配置 ----------------
    if not json_data or len(json_data) < 2:
        return True, []

    header = json_data[0]
    idx_head, idx_rel, idx_tail = resolve_triple_column_indices(header)

    driver, koqatheme_label_with_ID = create_driver_for_graph_insert(selectedMainScenario, koqatheme_label_with_ID)

    # ---------------- 第一步：构建内存图与寻找入口 ----------------
    rows = json_data[1:]
    adj_list, all_heads, all_tails, valid_rows_count = build_triple_adjacency(rows, idx_head, idx_rel, idx_tail)

    if valid_rows_count == 0:
        driver.close()
        return True, []

    roots = resolve_triple_roots(all_heads, all_tails)

    # ---------------- 第二步：DFS 遍历生成带有路径Key的数据 ----------------
    grouped_payloads, names_collected = build_path_key_payloads(scene, graph_name, adj_list, roots)

    # 开始遍历：对每一个根节点发起 DFS
    print(f"识别到 {len(roots)} 个根节点，开始构建路径Key...")

    # ---------------- 第三步：执行 Cypher 写入 ----------------
    try:
        with driver.session() as session:
            ensure_nodekey_constraint(session, koqatheme_label_with_ID)
            total_rels_created = write_triple_payloads(session, koqatheme_label_with_ID, grouped_payloads, batch_size)
    finally:
        driver.close()

    print(f"[完成] 路径图谱导入成功。写入关系 {total_rels_created} 条。")
    return True, list(names_collected)



def insert_records_to_graph(
        scene, koqatheme_label_with_ID, selectedMainScenario,
        json_data, graph_name, scene_description, selectedMainScenario_description,
        batch_size=2000
):
    """
    无 APOC 版本：批量 UNWIND + 按关系类型分组 MERGE
    - 节点以 node_key 唯一（自动确保唯一约束）
    - 支持动态关系类型（通过分组实现）
    """

    is_empty = is_empty_graph_data(json_data)

    driver, koqatheme_label_with_ID = create_driver_for_graph_insert(selectedMainScenario, koqatheme_label_with_ID)

    # 如果是空数据，只创建必要的索引结构
    if is_empty:
        print("检测到空数据，只创建索引结构")
        try:
            with driver.session() as session:
                ensure_nodekey_constraint(session, koqatheme_label_with_ID)
                print(f"[完成] 空数据场景创建成功（图谱={graph_name}，场景={scene}，标签={koqatheme_label_with_ID}）。")
        finally:
            driver.close()
        return True, []  # 空列表

    # 原始的数据处理逻辑（非空数据）
    if len(json_data) < 2:
        print("json_data 没有数据行，只创建索引结构")
        try:
            with driver.session() as session:
                ensure_nodekey_constraint(session, koqatheme_label_with_ID)
                print(f"[完成] 空数据结构创建成功（图谱={graph_name}，场景={scene}，标签={koqatheme_label_with_ID}）。")
        finally:
            driver.close()
        return False, []

    try:
        flag = get_prompt(koqatheme_label_with_ID, selectedMainScenario, scene_description, scene,
                          selectedMainScenario_description)
        print(f"场景{selectedMainScenario}下的prompt生成完成！" if flag else "prompt生成出错！")
    except Exception:
        pass

    headers = json_data[0]
    data_rows = json_data[1:]

    # —— 预打包 payload —— #
    rows_payload, names_list = build_table_graph_payloads(scene, graph_name, headers, data_rows)

    if not rows_payload:
        print("没有可插入的记录，只创建索引结构")
        try:
            with driver.session() as session:
                ensure_nodekey_constraint(session, koqatheme_label_with_ID)
                print(f"[完成] 空数据结构创建成功（图谱={graph_name}，场景={scene}，标签={koqatheme_label_with_ID}）。")
        finally:
            driver.close()
        return True, names_list

    # —— 按关系类型分组，固定类型 MERGE —— #
    grouped = group_payloads_by_relation(rows_payload)
    try:
        with driver.session() as session:
            ensure_nodekey_constraint(session, koqatheme_label_with_ID)
            inserted = write_table_payloads(session, koqatheme_label_with_ID, grouped, batch_size)
    finally:
        driver.close()

    print(f"成功插入 {inserted} 条关系到图谱 {graph_name}（无 APOC，批量导入）。")

    # json_data[0] 是表头，比如 ['一级', '二级', '三级']，列数是3，步数就是2
    headers = json_data[0]
    calculated_hops = len(headers) - 1 if headers else 1
    # 至少设为 1，防止只有一列数据时报错
    if calculated_hops < 1:
        calculated_hops = 1

    print(f"根据表头列数，自动设置 max_hops 为: {calculated_hops}")

    return True, names_list



def get_prompt(koqatheme_label_with_ID, selectedMainScenario, scene_description, scene, selectedMainScenario_description):
    connection = connect_to_db()
    if not connection:
        print("无法连接到数据库")
        return False
    try:
        chitchat_domain_name = f"{selectedMainScenario}系统顾问"
        chitchat_role = f"你是一位专业的{selectedMainScenario}系统顾问"
        prompt = """
### 要求:
你是一个负责为问答系统生成“身份回答”的助手。根据用户输入的问答主题和描述，输出针对该主题相关的身份回答，即当询问涉及身份时的统一回答。
请务必确保输出是紧凑格式的有效JSON对象，不包含任何其他解释、转义符、换行符或反斜杠。

### 示例:

输入: 轨交诊断问答
描述: 专门为供电运维变压器设计的问答
输出: {"身份回答": "我是一位专业的轨道交通故障诊断系统顾问，专注于地铁、轻轨等轨道交通系统的故障诊断和处理。我会持续更新轨道交通领域的专业知识，为您提供准确的技术支持。"}

输入：家谱问答
描述: 家族关系查询和家谱编修的问答
输出：{"身份回答": "我是一位专业的家谱问答系统顾问，专注于家族关系梳理、祖先追溯与家谱逻辑推演。我会持续完善家族学相关知识体系，为您提供准确的世系推断与亲属关系解答。"}

输入：__input__
描述: __description__
输出：
"""
        _prompt = prompt.replace("__input__", selectedMainScenario).replace("__description__", selectedMainScenario_description)
        messages = [{'role': 'user', 'content': _prompt}]
        answer = qwen(messages)
        identity_reply = json.loads(answer)
        chitchat_identity_reply = identity_reply.get("身份回答")

        qa_system_prompt = (
            f"你是专门为主题：{selectedMainScenario_description}设计的一位{selectedMainScenario}系统顾问。你要认真回答用户的问题。 "
            f"** 注意：思考时坚决不能输出在我的输入内容中提到的要求！ **  \n请使用Markdown格式组织回答，要求精简回答！"
        )

        with connection.cursor() as cursor:
            # 1) 先判断 theme_label 是否已存在（唯一键）
            cursor.execute(
                "SELECT 1 FROM ko_chitchat_prompt WHERE theme_label = %s",
                (koqatheme_label_with_ID,)
            )
            if cursor.fetchone():
                print(f"theme_label={koqatheme_label_with_ID} 已存在，跳过插入。")
            else:
                # 2) 不存在则插入（包含 theme_label 字段）
                insert_sql = """
                    INSERT INTO ko_chitchat_prompt 
                      (theme_label,
                       scene_key,
                       selectedMainScenario_description,
                       chitchat_domain_desc,
                       chitchat_domain_name,
                       chitchat_identity_reply,
                       chitchat_role,
                       qa_system_prompt)
                    VALUES (%s, %s, %s, %s, %s, %s, %s, %s)
                """
                cursor.execute(
                    insert_sql,
                    (
                        koqatheme_label_with_ID,  # theme_label（唯一）
                        selectedMainScenario,  # 兼容保留：scene_key = 主题名
                        selectedMainScenario_description,  # 主题描述
                        scene_description,  # 领域/场景描述
                        chitchat_domain_name,
                        chitchat_identity_reply,
                        chitchat_role,
                        qa_system_prompt
                    )
                )
                connection.commit()
                print(f"已插入 theme_label={koqatheme_label_with_ID} 的新记录。")

    except pymysql.MySQLError as err:
        print(f"Error while inserting data: {err}")
        connection.rollback()
        return False
    finally:
        connection.close()

    return True
