from ..engine_dependencies.graph_rule_queries.kdzn_rule_ent import getkoqathemeWithpermission


async def handle_get_koqatheme_with_permission(userID: str):
    """接口 get_koqathemeWithpermission：查询用户有权限访问的主题。"""
    return {"koqatheme": getkoqathemeWithpermission(userID)}
