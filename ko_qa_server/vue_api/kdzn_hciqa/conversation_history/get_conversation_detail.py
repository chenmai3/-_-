import pymysql
from fastapi import Request
from fastapi.responses import JSONResponse

from ..shared import connect_to_db, parse_history_qa


async def handle_get_conversations(request: Request):
    """接口 get_conversations：按 qid 查询单个会话的问答历史。"""
    try:
        query_data = await request.json()
    except ValueError:
        return JSONResponse({"message": "请求内容必须为 JSON 对象"}, status_code=400)
    qid = query_data.get("qid") if isinstance(query_data, dict) else None
    if not isinstance(qid, (str, int)) or not str(qid).strip():
        return JSONResponse({"message": "缺少有效的会话 ID"}, status_code=400)
    db_connection = connect_to_db()
    history_qa = None

    if not db_connection:
        return JSONResponse({"message": "数据库连接失败，无法加载历史消息"}, status_code=503)

    if db_connection:
        try:
            with db_connection.cursor(pymysql.cursors.DictCursor) as cursor:
                sql = """
                    SELECT title, history_qa
                    FROM ko_kdzn_history_conversations
                    WHERE id = %s
                    LIMIT 1
                """
                cursor.execute(sql, (qid,))
                row = cursor.fetchone()
                if row:
                    parsed = parse_history_qa(row.get("history_qa"))
                    if parsed is None:
                        title = row.get("title") or ""
                        history_qa = [{"query": title, "answer": "思考中断，暂无回答..."}]
                    else:
                        history_qa = [parsed] if isinstance(parsed, dict) else parsed
                        if not isinstance(history_qa, list) or not all(isinstance(item, dict) for item in history_qa):
                            return JSONResponse({"message": "历史消息格式异常，无法加载"}, status_code=500)
                else:
                    return JSONResponse({"message": "该历史会话不存在或已被删除"}, status_code=404)
        except pymysql.MySQLError:
            return JSONResponse({"message": "历史消息查询失败，请稍后重试"}, status_code=500)
        finally:
            db_connection.close()

    return JSONResponse({"q_history": history_qa})
