from fastapi import Request
from fastapi.responses import JSONResponse

from ..engine_dependencies.graph_rule_queries.family_graph_queries import family_relation_states
from ..engine_dependencies.graph_rule_queries.general_query_state import general_query_states
from ..shared import connect_to_db


async def handle_delete_conversation_by_id(request: Request):
    """接口 deleteConversationById：根据 qid 和 userId 删除历史会话。"""
    data = await request.json()
    qid = data.get("qid")
    user_id = data.get("userId")

    if not all([qid, user_id]):
        return JSONResponse(
            {"status": "error", "message": "请求失败，缺少 qid 或 userId 参数"},
            status_code=400,
        )

    db_connection = connect_to_db()
    if not db_connection:
        return JSONResponse({"status": "error", "message": "数据库连接失败"}, status_code=500)

    try:
        with db_connection.cursor() as cursor:
            sql_delete = "DELETE FROM ko_kdzn_history_conversations WHERE id = %s AND user_id = %s"
            cursor.execute(sql_delete, (qid, user_id))
            db_connection.commit()
            family_relation_states.clear(qid)
            general_query_states.clear(qid)
    except Exception as exc:
        return JSONResponse({"status": "error", "message": f"服务器内部错误: {str(exc)}"}, status_code=500)
    finally:
        db_connection.close()

    return JSONResponse({"status": "success", "message": "会话已成功删除"})
