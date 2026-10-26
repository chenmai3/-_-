import json
from pathlib import Path

import pymysql
from fastapi import Request
from fastapi.responses import JSONResponse
from starlette.concurrency import run_in_threadpool

from .common import (
    LOCAL_ANALYSIS_FILE_ROOT,
    SERVER_ROOT,
    USER_VECTOR_STORES_ROOT,
    connect_to_db,
    frontend_error,
    frontend_success,
    han2pinyin_concat,
)


from .dependencies.graph_rule_queries.cypher_tool import (
    insert_records_to_graph,
    insert_records_to_graph_jiapu,
    insert_triples_to_graph,
    query_new_neo4j,
)


GRAPH_HEADER = ["根节点", "类型", "头实体", "关系", "尾实体"]
JIAPU_HEADER = ["编号", "父亲编号", "配偶编号", "姓名", "性别", "简介", "字辈", "世代"]


def get_request_user_id(payload: dict) -> str:
    return str(payload.get("userId") or payload.get("userID") or "").strip()


def is_truly_empty_data(json_data):
    # insert_new_rule 接口内部函数：判断上传表格是否没有任何有效单元格。
    if not json_data:
        return True
    for row in json_data:
        if row and any(cell is not None and str(cell).strip() != "" for cell in row):
            return False
    return True


def validate_and_annotate_data(json_data: list, scene: str):
    # insert_new_rule 接口内部函数：校验表头和第二列场景是否与前端选择一致。
    if not json_data or len(json_data) < 2:
        if not json_data:
            return True, None
        headers = json_data[0]
        header_errors = []
        for i, header in enumerate(headers):
            if not str(header).strip():
                header_errors.append(f"第 {i + 1} 列缺少表头")
        if not headers or str(headers[0]).strip() != "根节点":
            header_errors.append("第一列表头必须为 '根节点'")
        if not header_errors:
            return True, None
        annotated_headers = headers + ["校验错误"]
        error_row = ["" for _ in headers] + ["; ".join(header_errors)]
        return False, [["填写错误反馈"], ["1.注意：请修改文件中标明的校验错误；\n2.修改完成后请删除前两行后再进行上传；"], annotated_headers, error_row]

    headers = json_data[0]
    data_rows = json_data[1:]
    is_valid = True
    annotated_data = []
    header_errors = []

    for i, header in enumerate(headers):
        if not str(header).strip():
            header_errors.append(f"第 {i + 1} 列缺少表头")
    if not headers or str(headers[0]).strip() != "根节点":
        header_errors.append("第一列表头必须为 '根节点'")

    annotated_data.append(headers + ["校验错误"])
    first_scene_value = None
    for row_index, row in enumerate(data_rows):
        row_errors = []
        if not isinstance(row, list) or len(row) < 2:
            row_errors.append("行格式错误或列数不足")
        else:
            cell_value = str(row[1]).strip()
            if cell_value != scene:
                row_errors.append(f"场景名应为'{scene}'，实际为'{cell_value}'")
            if row_index == 0:
                first_scene_value = cell_value
            elif cell_value != first_scene_value:
                row_errors.append(f"场景名与第一行'{first_scene_value}'不一致")

        if row_index == 0 and header_errors:
            row_errors = header_errors + row_errors

        error_message = "; ".join(row_errors)
        if error_message:
            is_valid = False
        annotated_data.append(row + [error_message])

    return (True, None) if is_valid else (False, annotated_data)


def build_theme_label(selected_main_scenario: str, user_id: str) -> str:
    # insert_new_rule/delete_kdzn_test_data 公共函数：生成 Neo4j 标签。
    if selected_main_scenario == "轨交诊断":
        return "kedazhineng"
    if selected_main_scenario == "家谱问答":
        return "huaputong"
    return f"{han2pinyin_concat(selected_main_scenario)}_{user_id}"


def graph_theme_label(selected_main_scenario: str, user_id: str) -> str:
    # get_scene_entities internal helper: keep graph-query labels aligned with graph insert logic.
    if selected_main_scenario == "轨交诊断":
        return "kedazhineng"
    if selected_main_scenario in ("家谱问答", "家谱主题问答"):
        return "jiapuwenda"
    return f"{han2pinyin_concat(selected_main_scenario)}_{user_id}"


def graph_kg(selected_main_scenario: str) -> str:
    # get_scene_entities internal helper: choose the Neo4j data source for the theme.
    if selected_main_scenario == "轨交诊断":
        return "kdzn"
    if selected_main_scenario in ("家谱问答", "家谱主题问答"):
        return "jiapu"
    return ""


def quote_neo4j_label(label: str) -> str:
    # get_scene_entities internal helper: prevent label injection while keeping Neo4j backtick syntax.
    return f"`{str(label or '').replace('`', '')}`"


def normalize_scene_entity_payload(payload: dict):
    # get_scene_entities internal helper: accept parameter names used by the three Vue pages.
    selected_main_scenario = (
        payload.get("selectedMainScenario")
        or payload.get("selectedMainTopic")
        or payload.get("theme")
        or payload.get("koqatheme")
        or ""
    )
    scene = (
        payload.get("selectedScenario")
        or payload.get("scene")
        or payload.get("koqascenario")
        or ""
    )
    user_id = get_request_user_id(payload)
    return str(selected_main_scenario).strip(), str(scene).strip(), user_id


def get_theme_label_from_permission(selected_main_scenario: str, scene: str):
    # get_scene_entities internal helper: prefer the theme_label recorded by the permission table.
    connection = connect_to_db()
    if not connection:
        return None
    try:
        with connection.cursor() as cursor:
            cursor.execute(
                """
                SELECT theme_label
                FROM ko_theme_permission
                WHERE theme_name = %s
                  AND scene_name = %s
                LIMIT 1
                """,
                (selected_main_scenario, scene),
            )
            row = cursor.fetchone()
            if not row:
                return None
            if isinstance(row, (tuple, list)):
                return row[0]
            if isinstance(row, dict):
                return row.get("theme_label")
            return None
    except pymysql.MySQLError as exc:
        print(f"[graph_construct] query theme_label failed: {exc}")
        return None
    finally:
        connection.close()


def get_scene_entity_labels(selected_main_scenario: str, scene: str, user_id: str):
    # get_scene_entities internal helper: collect compatible label candidates for legacy and new graphs.
    candidates = [
        get_theme_label_from_permission(selected_main_scenario, scene),
        graph_theme_label(selected_main_scenario, user_id),
        build_theme_label(selected_main_scenario, user_id),
    ]
    if selected_main_scenario in ("家谱问答", "家谱主题问答"):
        candidates.extend(["jiapuwenda", "huaputong"])
    if selected_main_scenario == "轨交诊断":
        candidates.append("kedazhineng")

    labels = []
    seen = set()
    for label in candidates:
        label = str(label or "").strip()
        if not label or label in seen:
            continue
        seen.add(label)
        labels.append(label)
    return labels


def query_scene_entities(selected_main_scenario: str, scene: str, user_id: str):
    # get_scene_entities internal helper: start from the scene node and query all downstream entity names.
    theme_labels = get_scene_entity_labels(selected_main_scenario, scene, user_id)
    entities = []
    seen_keys = set()
    for theme_label in theme_labels:
        query = """
            MATCH (scene_node {name: $scene, type: $theme_label})
            MATCH path = (scene_node)-[*1..]->(entity)
            WHERE entity.name IS NOT NULL
            RETURN DISTINCT
                entity.name AS name,
                labels(entity) AS labels,
                properties(entity) AS properties
            ORDER BY name
        """
        rows = query_new_neo4j(
            query,
            parameters={"scene": scene, "theme_label": theme_label},
            kg=graph_kg(selected_main_scenario),
        )
        for row in rows:
            name = row.get("name")
            labels = list(row.get("labels") or [])
            properties = dict(row.get("properties") or {})
            entity_key = (
                str(name),
                str(properties.get("id", "")),
                str(properties.get("node_key", "")),
                ",".join(labels),
            )
            if entity_key in seen_keys:
                continue
            seen_keys.add(entity_key)
            entities.append({
                "name": name,
                "labels": labels,
                "properties": properties,
            })

    return {
        "selectedMainScenario": selected_main_scenario,
        "selectedScenario": scene,
        "themeLabels": theme_labels,
        "count": len(entities),
        "entities": entities,
    }


def insert_graph_rows(scene, theme_label, selected_main_scenario, json_data, filename, scene_description, theme_description):
    # insert_new_rule 接口内部函数：根据表头选择家谱、三元组或普通图谱入库逻辑。
    if not json_data or is_truly_empty_data(json_data):
        return True, []
    header = json_data[0]
    if header == JIAPU_HEADER:
        return insert_records_to_graph_jiapu(scene, theme_label, selected_main_scenario, json_data, filename, scene_description, theme_description)
    if header == GRAPH_HEADER:
        return insert_triples_to_graph(scene, theme_label, selected_main_scenario, json_data, filename, scene_description, theme_description)
    return insert_records_to_graph(scene, theme_label, selected_main_scenario, json_data, filename, scene_description, theme_description)


def find_original_file(user_id, selected_main_scenario, filename):
    # insert_new_rule 接口内部函数：兼容新相对目录和历史相对目录中的原始文件。
    candidates = [
        LOCAL_ANALYSIS_FILE_ROOT / f"{user_id}_file_vectorstorges" / selected_main_scenario / filename,
        SERVER_ROOT / f"{user_id}_file_vectorstorges" / selected_main_scenario / filename,
    ]
    for candidate in candidates:
        if candidate.exists():
            return candidate

    filename_stem = Path(filename).stem
    for root in {candidate.parent for candidate in candidates}:
        if not root.exists():
            continue
        for item in root.iterdir():
            if item.is_file() and item.stem == filename_stem:
                return item
    return None


def vectorize_original_file(user_id, selected_main_scenario, filename):
    # insert_new_rule 接口内部函数：图谱入库后对原始文件做主题级向量化；失败不阻断主流程。
    try:
        file_path = find_original_file(user_id, selected_main_scenario, filename)
        if not file_path:
            print(f"[graph_construct] 原始文件未找到，跳过向量化: user={user_id}, topic={selected_main_scenario}, filename={filename}")
            return False

        filetype = file_path.suffix.replace(".", "").upper()
        if not filetype:
            return False

        from ..kdzn_hciqa.engine_dependencies.knowledge_base_chatbot import Chatzxl

        topic_label = han2pinyin_concat(selected_main_scenario)
        vector_user_id = f"{user_id}_file_vectorstoregs/{topic_label}"
        vector_store_path = USER_VECTOR_STORES_ROOT / vector_user_id

        kochatbot = Chatzxl()
        kochatbot.init_database()
        if not vector_store_path.exists():
            vector_store_path.mkdir(parents=True, exist_ok=True)
            kochatbot.create_new_vector_stroes(vector_store_path)
            (vector_store_path / "doc_rangs.json").write_text(json.dumps({}, ensure_ascii=False, indent=4), encoding="utf-8")

        kochatbot.update_vector_stores(str(file_path), file_path.name, vector_user_id, filetype)
        return True
    except Exception as exc:
        print(f"[graph_construct] 原始文件向量化失败: {exc}")
        return False


def vectorize_entry_entities(selected_main_scenario, theme_label, scene, names_list):
    # insert_new_rule 接口内部函数：图谱入口实体向量化；失败不阻断主流程。
    if not names_list:
        return None
    try:
        from ..kdzn_hciqa.engine_dependencies.entity_vector_builder import (
            get_entity_vector,
        )
        return get_entity_vector(selected_main_scenario, theme_label, scene, names_list)
    except Exception as exc:
        print(f"[graph_construct] 入口实体向量化失败: {exc}")
        return None


async def handle_insert_new_rule(request: Request):
    # insert_new_rule 接口：负责前端抽取结果入 Neo4j/规则库。
    try:
        payload = await request.json()
        scene = payload["selectedScenario"]
        selected_main_scenario = payload.get("selectedMainScenario", "轨交诊断")
        json_data = payload.get("jsonData") or []
        filename = payload.get("filename") or ""
        scene_description = payload.get("scene_description") or ""
        theme_description = payload.get("selectedMainScenario_description") or ""
        user_id = get_request_user_id(payload)
        if not user_id:
            return frontend_error("缺少 userId/userID", status_code=400)

        theme_label = build_theme_label(selected_main_scenario, user_id)
        is_empty = is_truly_empty_data(json_data)
        if not is_empty and selected_main_scenario in ("轨交诊断", "农业QA"):
            is_valid, annotated_data = validate_and_annotate_data(json_data, scene)
            if not is_valid:
                return JSONResponse(content={
                    "data": {
                        "status": "validation_failed",
                        "msg": "您上传的文件填写有误，请点击下载错误提示文件，核对修改错误属性！",
                        "annotated_data": annotated_data,
                    },
                    "message": "validation_error",
                    "statusCode": 200,
                })

        success, names_list = await run_in_threadpool(
            insert_graph_rows,
            scene,
            theme_label,
            selected_main_scenario,
            json_data,
            filename,
            scene_description,
            theme_description,
        )

        if not success:
            return JSONResponse(content={
                "data": {"status": "failed", "msg": "图谱录入失败！"},
                "message": "error",
                "statusCode": 500,
            }, status_code=500)

        file_vector_result = await run_in_threadpool(vectorize_original_file, user_id, selected_main_scenario, filename)
        await run_in_threadpool(vectorize_entry_entities, selected_main_scenario, theme_label, scene, names_list)

        msg = "空数据场景创建成功！" if is_empty else "图谱录入成功！"
        return JSONResponse(content={
            "data": {
                "status": "success",
                "msg": msg,
                "fileVectorStatus": "success" if file_vector_result is True else "skip_or_failed",
            },
            "message": "success",
            "statusCode": 200,
        })
    except KeyError as exc:
        return frontend_error(f"缺少必要参数: {exc}", status_code=400)
    except Exception as exc:
        return JSONResponse(content={
            "data": {"status": "server_error", "msg": f"服务器内部错误: {exc}"},
            "message": "error",
            "statusCode": 500,
        }, status_code=500)


def truncate_table(connection, table_name, theme_label=None, scene=None):
    # delete_kdzn_test_data 接口内部函数：只删除当前场景和主题标签的规则记录。
    try:
        with connection.cursor() as cursor:
            if theme_label and scene:
                cursor.execute(f"DELETE FROM `{table_name}` WHERE `scene` = %s AND `theme_label` = %s;", (scene, theme_label))
            else:
                cursor.execute(f"TRUNCATE TABLE `{table_name}`;")
        connection.commit()
        return True, ""
    except pymysql.MySQLError as exc:
        connection.rollback()
        return False, str(exc)


def delete_all_kdzn_nodes(selected_main_scenario, theme_label, scene):
    # delete_kdzn_test_data 接口内部函数：删除当前主题/场景下 Neo4j 节点。
    try:
        query = f"MATCH (n:{theme_label} {{scene: '{scene}'}}) DETACH DELETE n"
        if selected_main_scenario == "轨交诊断":
            query_new_neo4j(query, kg="kdzn")
        elif selected_main_scenario in ("家谱问答", "家谱主题问答"):
            query_new_neo4j(query, kg="jiapu")
        else:
            query_new_neo4j(query, kg="")
        return {"status": True, "msg": "数据删除成功。"}
    except Exception as exc:
        return {"status": False, "msg": f"删除 Neo4j 数据时发生错误: {exc}"}


async def handle_get_scene_entities(request: Request):
    # get_scene_entities API: input theme and scene, output all graph entities in the scene.
    try:
        payload = await request.json()
        selected_main_scenario, scene, user_id = normalize_scene_entity_payload(payload)
        if not selected_main_scenario:
            return frontend_error("缺少主题参数 selectedMainScenario/selectedMainTopic/theme", status_code=400)
        if not scene:
            return frontend_error("缺少场景参数 selectedScenario/scene", status_code=400)

        data = await run_in_threadpool(
            query_scene_entities,
            selected_main_scenario,
            scene,
            user_id,
        )
        return frontend_success(data)
    except Exception as exc:
        return frontend_error(f"查询场景实体失败: {exc}", status_code=500)


async def handle_delete_kdzn_test_data(request: Request):
    # delete_kdzn_test_data 接口：删除当前场景图谱和规则数据。
    try:
        payload = await request.json()
        scene = payload["selectedScenario"]
        selected_main_scenario = payload["selectedMainScenario"]
        user_id = get_request_user_id(payload)
        if not user_id:
            return frontend_error("缺少 userId/userID", status_code=400)

        theme_label = build_theme_label(selected_main_scenario, user_id)
        neo4j_result = await run_in_threadpool(delete_all_kdzn_nodes, selected_main_scenario, theme_label, scene)

        db_success = False
        db_msg = ""
        connection = connect_to_db()
        if connection:
            try:
                if selected_main_scenario == "家谱问答":
                    db_success = True
                elif selected_main_scenario == "轨交诊断":
                    db_success, db_msg = truncate_table(connection, "ko_kdzn_rule_construct")
                else:
                    db_success, db_msg = truncate_table(connection, "ko_kdzn_rule_construct", theme_label, scene)
            finally:
                connection.close()
        else:
            db_msg = "数据库连接失败，无法清空规则表。"

        if neo4j_result["status"] and db_success:
            return JSONResponse(status_code=200, content={"statusCode": 200, "msg": "图谱数据和规则已全部成功删除！"})

        errors = []
        if not neo4j_result["status"]:
            errors.append(f"图谱数据删除失败: {neo4j_result['msg']}")
        if not db_success:
            errors.append(f"规则数据清空失败: {db_msg}")
        return JSONResponse(status_code=500, content={"statusCode": 500, "msg": f"操作未完全成功: {' | '.join(errors)}"})
    except KeyError as exc:
        return frontend_error(f"缺少必要参数: {exc}", status_code=400)
    except Exception as exc:
        return frontend_error(f"删除图谱数据失败: {exc}", status_code=500)
