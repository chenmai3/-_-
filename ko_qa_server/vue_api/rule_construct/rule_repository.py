from fastapi.responses import JSONResponse

from .common import connect_to_db, frontend_error, frontend_success
from .rule_database import (
    delete_records_by_rulename,
    get_label,
    get_label_with_userid,
    insert_new_data,
)


async def handle_new_rule_submit(payload: dict):
    # new_rule_submit 接口：保存手工生成或编辑后的规则。
    connection = connect_to_db()
    if not connection:
        return frontend_error("数据库连接失败", data="数据库保存失败！")

    try:
        scene = payload["scene"]
        selected_main_scenario = payload.get("selectedMainScenario", "轨交诊断")
        theme_label = get_label_with_userid(connection, selected_main_scenario, scene)
        if selected_main_scenario == "家谱问答":
            theme_label = "huaputong"
        if selected_main_scenario == "轨交诊断":
            theme_label = "kedazhineng"
        if not theme_label:
            return frontend_error("未找到主题对应的图谱标签", data="数据库保存失败！")

        rule_data = [
            selected_main_scenario,
            scene,
            payload["rulename"],
            payload["rulepath"],
            payload["getin4simi"],
            payload.get("inferenceRule_human", ""),
            payload.get("ruleEntry_human", ""),
        ]
        ok = insert_new_data(connection, rule_data, theme_label, scene, selected_main_scenario)
        if not ok:
            return frontend_success("数据库保存失败！", msg="error")
        return frontend_success("数据保存成功！")
    except Exception as exc:
        try:
            connection.rollback()
        except Exception:
            pass
        return frontend_error(f"规则提交失败: {exc}", data="数据库保存失败！")
    finally:
        try:
            connection.close()
        except Exception:
            pass


async def handle_sql_polling(payload: dict):
    connection = connect_to_db()
    if not connection:
        return frontend_error("数据库连接失败", data=[])

    try:
        selected_main_scenario = payload.get("selectedMainScenario", "轨交诊断")
        labels = get_label(connection, selected_main_scenario)
        if selected_main_scenario == "轨交诊断" and "kedazhineng" not in labels:
            labels.append("kedazhineng")
        if selected_main_scenario == "家谱问答" and "huaputong" not in labels:
            labels.append("huaputong")

        if not labels:
            return {
                "statusCode": 200,
                "data": [],
                "results": [],
                "labels": [],
                "msg": "success",
                "message": "success",
            }

        placeholders = ",".join(["%s"] * len(labels))
        sql = f"""
            SELECT *
            FROM ko_kdzn_rule_construct
            WHERE theme_label IN ({placeholders})
        """
        with connection.cursor() as cursor:
            cursor.execute(sql, labels)
            columns = [column[0] for column in cursor.description]
            rows = [dict(zip(columns, row)) for row in cursor.fetchall()]

        return {
            "statusCode": 200,
            "data": rows,
            "results": rows,
            "labels": labels,
            "msg": "success",
            "message": "success",
        }
    except Exception as exc:
        return frontend_error(f"规则列表查询失败: {exc}", data=[])
    finally:
        try:
            connection.close()
        except Exception:
            pass


async def handle_rule_delete(payload: dict):
    # rule_delete 接口：按规则名删除当前主题下的规则。
    connection = connect_to_db()
    if not connection:
        return frontend_error("数据库连接失败", data="规则删除失败！")

    try:
        rulename = payload["rulename"]
        selected_main_scenario = payload.get("selectedMainScenario", "轨交诊断")
        delete_records_by_rulename(connection, selected_main_scenario, [rulename])
        return JSONResponse({"msg": "规则删除成功！", "data": "规则删除成功！"})
    except Exception as exc:
        try:
            connection.rollback()
        except Exception:
            pass
        return frontend_error(f"规则删除失败: {exc}", data="规则删除失败！")
