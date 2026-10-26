from datetime import datetime

import pymysql
from fastapi import Request
from fastapi.responses import JSONResponse

from ..shared import connect_to_db


async def handle_get_history_conversations(request: Request):
    """接口 getHistoryConversations：查询指定用户的历史会话列表。"""
    query_data = await request.json()
    user_id = query_data["userId"]
    db_connection = connect_to_db()

    if not db_connection:
        return JSONResponse([], status_code=500)

    try:
        with db_connection.cursor(pymysql.cursors.DictCursor) as cursor:
            sql = """
                SELECT id, title, created_at, updated_at
                FROM ko_kdzn_history_conversations
                WHERE user_id = %s
                ORDER BY updated_at DESC
            """
            cursor.execute(sql, (user_id,))
            results = cursor.fetchall()

            for row in results:
                if isinstance(row.get("created_at"), datetime):
                    row["created_at"] = row["created_at"].isoformat()
                if isinstance(row.get("updated_at"), datetime):
                    row["updated_at"] = row["updated_at"].isoformat()

            return JSONResponse(results)
    except pymysql.MySQLError:
        return JSONResponse([], status_code=500)
    finally:
        db_connection.close()
