from .common import frontend_error, frontend_json_string
from .theme_repository import ThemePermissionRepository


theme_permissions = ThemePermissionRepository()


async def handle_get_koqatheme_with_permission(user_id: str):
    try:
        return frontend_json_string({"koqatheme": theme_permissions.list_themes(user_id)})
    except Exception as exc:
        return frontend_error(f"查询主题权限失败: {exc}")


async def handle_get_koqascenarios_with_permission(user_id: str, selected_main_topic: str):
    try:
        scenarios = theme_permissions.list_scenarios(selected_main_topic, user_id)
        return frontend_json_string({"koqascenarios": scenarios})
    except Exception as exc:
        return frontend_error(f"查询场景权限失败: {exc}")


async def handle_get_koqatheme():
    try:
        return frontend_json_string({"koqatheme": theme_permissions.list_themes()})
    except Exception as exc:
        return frontend_error(f"查询主题失败: {exc}")


async def handle_get_koqascenarios(selected_main_topic: str):
    try:
        return frontend_json_string({"koqascenarios": theme_permissions.list_scenarios(selected_main_topic)})
    except Exception as exc:
        return frontend_error(f"查询场景失败: {exc}")


async def handle_has_permission_to_add(payload: dict):
    try:
        allowed = theme_permissions.can_add(
            str(payload.get("theme_name") or ""),
            str(payload.get("scene_name") or ""),
            str(payload.get("userID") or ""),
        )
        return {"has_permissiontoadd": allowed}
    except Exception as exc:
        return frontend_error(f"查询添加权限失败: {exc}")


async def handle_delete_permission(payload: dict):
    try:
        allowed = theme_permissions.can_delete(
            str(payload.get("koqatheme") or ""),
            str(payload.get("selectedScenario") or ""),
            str(payload.get("userID") or ""),
        )
        return {"hasPermission": allowed}
    except Exception as exc:
        return frontend_error(f"查询删除权限失败: {exc}")


async def handle_add_theme_permission(payload: dict):
    try:
        ok, message, info = theme_permissions.create(payload)
        if ok:
            return {
                "koqatheme": "ok",
                "data": {"status": "success", "msg": message, **info},
            }
        return {"koqatheme": "error", "data": {"status": "error", "msg": message}}
    except Exception as exc:
        return frontend_error(f"主题权限保存失败: {exc}")


async def handle_delete_theme(payload: dict):
    try:
        ok = theme_permissions.delete(
            str(payload.get("koqatheme") or ""),
            str(payload.get("selectedScenario") or ""),
            str(payload.get("userid") or payload.get("userID") or ""),
        )
        return {"koqatheme": ok}
    except Exception as exc:
        return frontend_error(f"主题场景删除失败: {exc}")
