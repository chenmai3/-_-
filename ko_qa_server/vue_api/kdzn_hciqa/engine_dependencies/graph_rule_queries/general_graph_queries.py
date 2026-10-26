from typing import List, Tuple

import pymysql

from ....common.neo4j_client import query_new_neo4j
from ....common.paths import (
    CONFIG_PATH,
    JIAPU_ENTITY_VECTOR_STORE,
    rule_entity_vector_store_path,
)
from .graph_query_utils import (
    get_chinese_properties,
    han2pinyin_concat,
    normalize_rule_paths,
    record_payload,
    remove_substrings,
)
from .general_query_state import (
    EMPTY_RES,
    SearchResult,
    general_query_states,
)
from .kdzn_rule_ent import kdzn_file_rules_kdzn_generate
from .rule_template import render_cypher
from .tog_path_explorer import (
    TogSearchContext,
    run_tog_search as explore_tog_paths,
)
from .vector_matching import (
    ensure_rule_entity_vector_store,
    get_best_match,
    get_best_rule_match,
    has_faiss_store,
)

with CONFIG_PATH.open(encoding="utf-8") as f:
    import yaml
    cfg = yaml.safe_load(f)

Triplet = Tuple[str, str, str]

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


def resolve_theme_label_with_permission(userid, scene_choose):
    """
    根据主题权限修正 label_with_ID。

    private:
        当前用户自己的主题，继续用 当前userid

    public:
        如果当前用户访问的是别人创建的 public 主题，
        则改成 create_id 对应的 theme_label。

    返回：
        label, label_with_ID, real_userid
    """
    label = han2pinyin_concat(scene_choose)
    userid = str(userid)

    # 默认兜底：当前用户自己的 label
    default_label_with_id = f"{label}_{userid}"

    connection = None
    try:
        connection = connect_to_db()
        with connection.cursor(pymysql.cursors.DictCursor) as cursor:
            # 1. 优先查当前用户自己创建的主题
            sql_owner = """
                SELECT 
                    theme_name,
                    theme_label,
                    topic_permission,
                    create_id
                FROM ko_theme_permission
                WHERE theme_name = %s
                  AND create_id = %s
                ORDER BY id DESC
                LIMIT 1
            """
            cursor.execute(sql_owner, (scene_choose, userid))
            row = cursor.fetchone()

            # 2. 如果当前用户不是创建者，再查 public 主题
            if not row:
                sql_public = """
                    SELECT 
                        theme_name,
                        theme_label,
                        topic_permission,
                        create_id
                    FROM ko_theme_permission
                    WHERE theme_name = %s
                      AND topic_permission = 'public'
                ORDER BY id DESC
                LIMIT 1
                """
                cursor.execute(sql_public, (scene_choose,))
                row = cursor.fetchone()

        if not row:
            print("[主题权限判断] 未查到主题权限记录，使用默认 label_with_ID：", default_label_with_id)
            return label, default_label_with_id, userid

        topic_permission = row.get("topic_permission")
        create_id = str(row.get("create_id") or userid)
        theme_label = row.get("theme_label")

        print("[主题权限判断] scene_choose:", scene_choose)
        print("[主题权限判断] topic_permission:", topic_permission)
        print("[主题权限判断] create_id:", create_id)
        print("[主题权限判断] theme_label:", theme_label)

        # public 主题：使用创建者对应的 theme_label
        if topic_permission == "public":
            if theme_label:
                label_with_id = theme_label
            else:
                label_with_id = f"{label}_{create_id}"

            print("[主题权限判断] public主题，切换 label_with_ID：", label_with_id)
            return label, label_with_id, create_id

        # private 或其他情况：如果数据库有 theme_label 就用数据库的
        if theme_label:
            print("[主题权限判断] private主题，使用数据库 theme_label：", theme_label)
            return label, theme_label, create_id

        print("[主题权限判断] 使用默认 label_with_ID：", default_label_with_id)
        return label, default_label_with_id, userid

    except Exception as e:
        print("[主题权限判断异常] 使用默认 label_with_ID：", default_label_with_id, e)
        return label, default_label_with_id, userid

    finally:
        if connection:
            connection.close()

def find_general(
    userid,
    q,
    wt,
    fo,
    scene_choose,
    fuzzy_entity,
    fuzzy_relation,
    is_duolun,
    embedding,
    model_client,
    top_k,
    max_rounds,
    session_id=None,
):
    cache_manager = general_query_states.get(session_id, fo)
    with cache_manager.lock:
        if not is_duolun:
            cache_manager.clear()
        results = _find_general(
            userid,
            q,
            wt,
            fo,
            scene_choose,
            fuzzy_entity,
            fuzzy_relation,
            is_duolun,
            embedding,
            model_client,
            top_k,
            max_rounds,
            cache_manager,
        )
        cache_manager.replace(results)
        return results


def _find_general(
    userid,
    q,
    wt,
    fo,
    scene_choose,
    fuzzy_entity,
    fuzzy_relation,
    is_duolun,
    embedding,
    model_client,
    top_k,
    max_rounds,
    cache_manager,
):
    print("cache", cache_manager.get_paths())
    print(scene_choose)

    # 根据 public/private 权限修正 label_with_ID
    label, label_with_ID, real_userid = resolve_theme_label_with_permission(userid, scene_choose)

    print("label:", label)
    print("label_with_ID:", label_with_ID)
    print("原始userid:", userid)
    print("实际使用userid:", real_userid)
    table_name = "ko_kdzn_rule_construct"
    general_file_rules = kdzn_file_rules_kdzn_generate(table_name, scene_choose)  # 从mysql加载规则
    # print(general_file_rules)
    if scene_choose == '家谱主题问答':
        rules = [r for lst in general_file_rules.values() for r in lst]
        print("家谱主题问答下所有的规则：", rules)
    else:
        rules = general_file_rules.get(fo)
        print("根据场景拿到的规则列表：", rules)
    rrule = None

    tog_context = TogSearchContext(
        label_with_id=label_with_ID,
        file_ontology=fo,
        scene_choose=scene_choose,
        rewritten_query=wt,
        is_multi_turn=is_duolun,
        top_k=top_k,
        fuzzy_entity=fuzzy_entity,
        max_rounds=max_rounds,
    )

    def fallback_to_tog(reason=""):
        return explore_tog_paths(
            reason,
            context=tog_context,
            cache_manager=cache_manager,
            embedding=embedding,
            event_queue=q,
        )
    if rules is None or len(rules) == 0:
        return fallback_to_tog("规则列表为空")
    else:
        file_rules = [rule["rule_name"] for rule in rules]

        # 根据 qwen 向量相似度获取当前文件中与 fuzzy_relation 最相近的规则头
        max_rule_score, candidate_rule_name = get_best_rule_match(
            fuzzy_relation,
            file_rules,
            model_client
        )

        print(
            f"规则候选匹配：“{fuzzy_relation}”从{len(file_rules)}个规则头中找到最高候选:"
            f"{candidate_rule_name}，得分：{max_rule_score:.2f}"
        )

        # ================================
        # 关键修改：设置有效命中阈值
        # ================================
        RULE_MATCH_THRESHOLD = 0.50

        # 如果只有 1 个规则头，阈值再提高一点，避免“唯一候选”被误认为命中
        if len(file_rules) == 1:
            RULE_MATCH_THRESHOLD = 0.55

        # 分数不够，不认为命中规则，直接走 TOG
        if not candidate_rule_name or max_rule_score < RULE_MATCH_THRESHOLD:
            return fallback_to_tog(
                f"规则列表存在，但未命中有效规则；最高候选为：{candidate_rule_name}，"
                f"得分：{max_rule_score:.2f}，阈值：{RULE_MATCH_THRESHOLD:.2f}"
            )

        # 只有超过阈值，才认为是真的命中规则
        match_rule_name = candidate_rule_name

        print(
            f"规则有效命中：“{fuzzy_relation}”匹配到规则:{match_rule_name}，"
            f"得分：{max_rule_score:.2f}"
        )

        rrule = None
        for rule in rules:
            if rule["rule_name"] == match_rule_name:
                rrule = rule
                break

        if rrule is None:
            return fallback_to_tog("规则匹配到了规则名，但没有找到对应规则对象")
    if not rrule or not isinstance(rrule, dict):
        return fallback_to_tog("rrule为空或格式异常")
    if scene_choose == "家谱主题问答":
        query_neo4j_res = query_new_neo4j(rrule["getIn4simi"], kg="jiapu")
        print('家谱主题问答')
        rule_in_ents = []  # 得到的检索实体（规则的输入实体）
        entstr2RIName = {}
        for record in query_neo4j_res:
            ent = []
            payload = record_payload(record)
            if "R1Name" in payload:
                ent.append(payload["R1Name"])
            if "R2Name" in payload:
                ent.append(payload["R2Name"])
            if "RIName" in payload:
                ent.append(payload["RIName"])
            ent2str = "".join([e for e in ent if e])  # e 既非 None 也非空串才拼
            ri_name = payload.get("RIName")
            if ent2str and ri_name:
                rule_in_ents.append(ent2str)
                entstr2RIName[ent2str] = ri_name
    elif scene_choose == '轨交诊断':
        query_neo4j_res = query_new_neo4j(rrule["getIn4simi"], kg="kdzn")
        rule_in_ents = []  # 得到的检索实体（规则的输入实体）
        entstr2RIName = {}
        for record in query_neo4j_res:
            print(record)
            ent = []
            payload = record_payload(record)
            if "R1Name" in payload:
                ent.append(payload["R1Name"])
            if "R2Name" in payload:
                ent.append(payload["R2Name"])
            if "RIName" in payload:
                ent.append(payload["RIName"])
            ent2str = "".join([e for e in ent if e])  # e 既非 None 也非空串才拼
            ri_name = payload.get("RIName")
            if ent2str and ri_name:
                rule_in_ents.append(ent2str)
                entstr2RIName[ent2str] = ri_name
    else:
        query_neo4j_res = query_new_neo4j(rrule["getIn4simi"], kg='')
        print(query_neo4j_res)
        rule_in_ents = []  # 得到的检索实体（规则的输入实体）
        entstr2RIName = {}
        for record in query_neo4j_res:
            ent = []
            payload = record_payload(record)
            if "R1Name" in payload:
                ent.append(payload["R1Name"])
            if "R2Name" in payload:
                ent.append(payload["R2Name"])
            if "RIName" in payload:
                ent.append(payload["RIName"])
            ent2str = "".join([e for e in ent if e])  # e 既非 None 也非空串才拼
            ri_name = payload.get("RIName")
            if ent2str and ri_name:
                rule_in_ents.append(ent2str)
                entstr2RIName[ent2str] = ri_name
    print("entstr2RIName", entstr2RIName)
    if not rule_in_ents:
        return fallback_to_tog("规则入口查询未返回可匹配实体")
    #     匹配相似实体
    # _, match_ent_span = getBest_phrase(fuzzy_entity, rule_in_ents)  # 词频匹配
    # match_ent_score, match_ent_span = get_best_rule_match(fuzzy_entity, rule_in_ents, model_client)
    rid = rrule["rid"]
    print("规则对应的rid:", rid)
    if scene_choose == "家谱主题问答":
        path = JIAPU_ENTITY_VECTOR_STORE
        match_ent_score, match_ent_span = get_best_match(fuzzy_entity, path, embedding)
        match_ent = match_ent_span
    else:
        path = rule_entity_vector_store_path(rid)
        if not has_faiss_store(path):
            ensure_rule_entity_vector_store(path, rule_in_ents, embedding)
        match_ent_score, match_ent_span = get_best_match(fuzzy_entity, path, embedding)
        if match_ent_span is None:
            match_ent_score, match_ent_span = get_best_rule_match(fuzzy_entity, rule_in_ents, model_client)
        match_ent = entstr2RIName.get(match_ent_span, match_ent_span)
    # match_ent_score, match_ent_span = get_best_rule_match(fuzzy_entity, rule_in_ents, model_client)
    # match_ent = entstr2RIName.get(match_ent_span)
    match_ent_score = match_ent_score if match_ent_score is not None else 0.0

    print(
        f"实体段匹配：从{len(rule_in_ents)}个实体段中匹配结果:{match_ent_span}，得分：{match_ent_score:.2f}")
    # if match_ent_score < 0.1:
    #     results = []
    #     while len(results) < top_k:
    #         results.append(EMPTY_RES)
    #     return results

    # 检索结果
    cyphers = normalize_rule_paths(rrule["rule_path"])
    result_names: List[str] = []
    paths: List[str] = []
    path2triplet: List[List[Triplet]] = []
    path_triplets: List[Triplet] = []
    if match_ent is not None:
        for cypher in cyphers:
            query_ = render_cypher(
                cypher,
                {"RIName": match_ent, "entityname": match_ent},
                fuzzy_entity,
            )
            print(query_)
            if scene_choose == "家谱主题问答":
                cypher_result = query_new_neo4j(query_, kg='jiapu')
            else:
                cypher_result = query_new_neo4j(query_, kg='')
            print("cypher_result", cypher_result)
            for record in cypher_result:
                path = record["p"]
                relationships = list(path.relationships)
                path_str = ""
                p2ts = []
                for i in range(len(relationships)):
                    nodes = relationships[i].nodes
                    start_node = nodes[0]["name"]
                    # nodes[0]._properties
                    end_node = nodes[1]["name"]
                    rel = relationships[i]["name"]
                    if rel is None:
                        rel = relationships[i].type
                    if rel == "kedazhineng" or rel == "KedaIntelligent" or rel == "kdzn":
                        rel = relationships[i]["edge_name"]
                    if rel is None:
                        rel = relationships[i]["type"]
                    if isinstance(rel, str):
                        if rel.startswith("包含-"):
                            rel = "包含"
                    if (start_node, rel, end_node) not in path_triplets:
                        path_triplets.append((start_node, rel, end_node))
                    p2ts.append((start_node, rel, end_node))
                    # 增加中文属性三元组到path_triplets
                    start_node_chinese_properties = get_chinese_properties(nodes[0])
                    end_node_chinese_properties = get_chinese_properties(nodes[1])

                    for node, properties in [(start_node, start_node_chinese_properties),
                                             (end_node, end_node_chinese_properties)]:
                        for k, v in properties.items():
                            if k == "requirement":
                                k = "要求"
                            path_triplets.append((node, k, v)) if (node, k, v) not in path_triplets else None
                            # p2ts.append((node, k, v)) if (node, k, v) not in p2ts else None
                if not p2ts:
                    continue
                if len(p2ts) > 1:
                    first_tri, second_tri = p2ts[0], p2ts[1]
                    if first_tri[0] in [second_tri[0], second_tri[2]]:  # 左向路径
                        path_str += f"{first_tri[2]}<-[{first_tri[1]}]-{first_tri[0]}"
                        tail_node = first_tri[0]

                    else:
                        path_str += f"{first_tri[0]}-[{first_tri[1]}]->{first_tri[2]}"
                        tail_node = first_tri[2]
                    for tri in p2ts[1:]:
                        if tail_node == tri[0]:
                            path_str += f"-[{tri[1]}]->{tri[2]}"
                            tail_node = tri[2]
                        else:
                            path_str += f"<-[{tri[1]}]-{tri[0]}"
                            tail_node = tri[0]
                else:
                    tri = p2ts[0]
                    path_str += f"-[{tri[1]}]->{tri[2]}"
                    tail_node = tri[2]
                result = tail_node
                result_names.append(result) if result not in result_names else None
                paths.append(path_str) if path_str not in paths else None
                path2triplet.append(p2ts) if p2ts not in path2triplet else None
    print(paths)
    paths_clean = remove_substrings([str(p) for p in paths])
    res = SearchResult(False, result_names, paths_clean, path2triplet, path_triplets, [])
    results = [res]
    while len(results) < top_k:
        results.append(EMPTY_RES)
    return results
