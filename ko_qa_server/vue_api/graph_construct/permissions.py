from .dependencies.graph_rule_queries.kdzn_rule_ent import (
    getkoqathemeWithpermission,
    koqascenariosWithpermission,
)
from fastapi.responses import JSONResponse
from .common import frontend_error, frontend_json_string, frontend_success


# async def handle_get_koqatheme_with_permission(user_id: str):
#     # get_koqathemeWithpermission 接口内部函数：按用户 ID 查询可见主题。
#     try:
#         return frontend_success({"koqatheme": getkoqathemeWithpermission(user_id)})
#     except Exception as exc:
#         return frontend_error(f"查询主题权限失败: {exc}")

async def handle_get_koqatheme_with_permission(user_id: str):
    """按用户 ID 查询可见主题。"""
    try:
        theme_list = getkoqathemeWithpermission(user_id)

        return JSONResponse(
            status_code=200,
            content={
                "koqatheme": theme_list
            },
        )
    except Exception as exc:
        return JSONResponse(
            status_code=500,
            content={
                "koqatheme": [],
                "msg": f"查询主题权限失败: {exc}",
                "message": f"查询主题权限失败: {exc}",
            },
        )


# async def handle_get_koqascenarios_with_permission(user_id: str, selected_main_topic: str):
#     # get_koqascenariosWithpermission 接口内部函数：按用户 ID 和主题查询可见场景。
#     try:
#         scenarios = koqascenariosWithpermission(user_id, selected_main_topic)
#         return frontend_success({"koqascenarios": scenarios})
#     except Exception as exc:
#         return frontend_error(f"查询场景权限失败: {exc}")

async def handle_get_koqascenarios_with_permission(
    user_id: str,
    selected_main_topic: str,
):
    """按用户 ID 和主题查询可见场景。"""
    try:
        scenarios = koqascenariosWithpermission(
            user_id,
            selected_main_topic,
        )

        return JSONResponse(
            status_code=200,
            content={
                "koqascenarios": scenarios
            },
        )
    except Exception as exc:
        error_message = f"查询场景权限失败: {exc}"

        return JSONResponse(
            status_code=500,
            content={
                "koqascenarios": [],
                "msg": error_message,
                "message": error_message,
            },
        )
