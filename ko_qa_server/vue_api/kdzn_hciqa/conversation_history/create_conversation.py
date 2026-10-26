from datetime import datetime

from fastapi import Request
from fastapi.responses import JSONResponse

from ..shared import connect_to_db


async def handle_upsert_conversation(request: Request):
    """接口 upsertConversation：创建一条新的历史会话记录。"""
    data = await request.json()
    qid = data.get("qid")
    user_id = data.get("userId")
    query_text = data.get("query")

    if not all([qid, user_id, query_text]):
        return JSONResponse({"status": "error", "message": "缺少必要参数"}, status_code=400)

    db_connection = connect_to_db()
    if not db_connection:
        return JSONResponse({"status": "error", "message": "数据库连接失败"}, status_code=500)

    try:
        with db_connection.cursor() as cursor:
            now = datetime.now()
            title = (query_text[:100] + "...") if len(query_text) > 100 else query_text
            sql_insert = """
                INSERT INTO ko_kdzn_history_conversations (id, user_id, title, created_at, updated_at)
                VALUES (%s, %s, %s, %s, %s)
            """
            cursor.execute(sql_insert, (qid, user_id, title, now, now))
            db_connection.commit()
    except Exception as exc:
        return JSONResponse({"status": "error", "message": str(exc)}, status_code=500)
    finally:
        db_connection.close()

    return JSONResponse({"status": "success", "message": "创建新会话成功"})
