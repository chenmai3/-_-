import re

from fastapi.responses import JSONResponse

from .common import connect_to_db, frontend_error, han2pinyin_concat
from .rule_database import get_label_with_userid
from .rule_path_core import query as query_entity_subgraph
from .rule_path_core import query_1, query_2


def extract_ri_candidates(records):
    candidates = []
    if isinstance(records, list):
        for record in records:
            if isinstance(record, dict) and record.get("RIName"):
                candidates.append(str(record["RIName"]))
                continue
            match = re.search(r"RIName=['\"](.+?)['\"]", str(record))
            if match:
                candidates.append(match.group(1))
    else:
        candidates.extend(re.findall(r"RIName=['\"](.+?)['\"]", str(records)))

    seen = set()
    return [item for item in candidates if not (item in seen or seen.add(item))]


def build_rulepath_with_entity(rulepath: str, entity_name: str) -> str:
    if "'{entityname}'" in rulepath or '"{entityname}"' in rulepath:
        return rulepath.replace("{entityname}", entity_name)
    return rulepath.replace("{entityname}", f"'{entity_name}'")


def resolve_theme_label(selected_main_scenario: str, scene: str, user_id: str = "") -> str:
    if selected_main_scenario == "轨交诊断":
        return "kedazhineng"
    if selected_main_scenario == "家谱问答":
        return "huaputong"

    connection = connect_to_db()
    if connection:
        try:
            label = get_label_with_userid(connection, selected_main_scenario, scene)
            if label:
                return label
        finally:
            try:
                connection.close()
            except Exception:
                pass

    label = han2pinyin_concat(selected_main_scenario)
    return f"{label}_{user_id}" if user_id else label


async def handle_neo4j_match_1(payload: dict):
    try:
        queryneo4j = payload.get("queryneo4j", "")
        rulepath = payload["rulepath"]
        selected_main_scenario = payload["selectedMainScenario"]
        scene = payload["scene"]

        if selected_main_scenario == "家谱问答":
            pattern = re.compile(r'\{\s*name\s*:\s*(["\'])\{entityname\}\1\s*\}')
            new_rulepath = pattern.sub("", rulepath).strip() + " limit 10"
            _, matched_triplets = query_1(selected_main_scenario, new_rulepath, scene)
            return JSONResponse({"q_match": matched_triplets})

        formatted_paths = query_2(selected_main_scenario, queryneo4j, scene)
        candidates = extract_ri_candidates(formatted_paths)
        for entity_name in candidates:
            new_rulepath = build_rulepath_with_entity(rulepath, entity_name)
            _, matched_triplets = query_1(selected_main_scenario, new_rulepath, scene)
            if matched_triplets:
                return JSONResponse({"q_match": matched_triplets})
        return JSONResponse({"q_match": []})
    except Exception as exc:
        return frontend_error(f"规则图谱匹配失败: {exc}", data=[])


async def handle_neo4j_match(payload: dict):
    try:
        queryneo4j = payload["queryneo4j"]
        selected_main_scenario = payload.get("selectedMainScenario", "轨交诊断")
        scene = payload.get("scene", "")
        _, matched_triplets = query_1(selected_main_scenario, queryneo4j, scene)
        return JSONResponse({"q_match": matched_triplets})
    except Exception as exc:
        return frontend_error(f"Neo4j 查询失败: {exc}", data=[])


async def handle_neo4j_query(payload: dict):
    try:
        scene = payload.get("selectedScenario") or payload.get("scene") or ""
        input_entity = payload.get("input_entityName") or payload.get("entityName") or ""
        user_id = str(payload.get("userId") or payload.get("userID") or "")
        selected_main_scenario = payload.get("selectedMainScenario", "轨交诊断")

        theme_label = resolve_theme_label(selected_main_scenario, scene, user_id)
        matched_paths, matched_triplets = query_entity_subgraph(
            theme_label,
            selected_main_scenario,
            scene,
            input_entity,
        )
        return JSONResponse({
            "matched_paths": matched_paths,
            "matched_triplets": matched_triplets,
            "data": matched_triplets,
            "statusCode": 200,
            "msg": "success",
            "message": "success",
        })
    except Exception as exc:
        return frontend_error(f"Neo4j 实体子图查询失败: {exc}", data=[])
