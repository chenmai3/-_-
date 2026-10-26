import yaml
from vue_api.common.paths import CONFIG_PATH

with CONFIG_PATH.open(encoding="utf-8") as f:
    cfg = yaml.safe_load(f)

import pymysql



def connect_to_db():
    try:
        connection = pymysql.connect(
            host=cfg["KO_database"]["host"],  # 数据库主机
            user=cfg["KO_database"]["user"],  # 数据库用户名
            password=cfg["KO_database"]["password"],  # 数据库密码
            database=cfg["KO_database"]["database"],
            charset=cfg["KO_database"]["charset"]
        )
        return connection
    except pymysql.MySQLError as err:
        print(f"Error: {err}")
        return None



def isadministrator(userID: str):  # 判断是否是管理员
    connection = connect_to_db()
    if not connection:
        print("无法连接到数据库")
        return False
    try:
        with connection.cursor() as cursor:
            query = "SELECT 1 FROM koqa_administrator where administrator=%s"
            cursor.execute(query, (userID,))
            result = cursor.fetchone()
            if result:
                return True
            else:
                return False
    except pymysql.MySQLError as err:
        print(f"数据库查询错误: {err}")
        return False
    except Exception as e:
        print(f"查询管理员用户时发生错误: {e}")
        return False
    finally:
        if connection:
            connection.close()



def koqascenariosWithpermission(userID, selectedMainTopic):
    connection = connect_to_db()
    if not connection:
        print("无法连接到数据库")
        return []
    try:
        with connection.cursor() as cursor:
            if not isadministrator(userID):
                cursor.execute(
                    "SELECT  scene_name FROM ko_theme_permission where theme_name=%s and(create_id=%s or "
                    "scene_permission='public') "
                    "AND scene_name IS NOT NULL AND scene_name != ''",
                    (selectedMainTopic, userID)
                )
            else:
                cursor.execute(
                    "SELECT  scene_name FROM ko_theme_permission where theme_name=%s  AND scene_name IS NOT NULL AND scene_name != ''",
                    (selectedMainTopic,)
                )
            result = cursor.fetchall()
            if result:
                # 将结果转换为列表形式
                theme_list = [row[0] for row in result]
                print(f"为用户id：{userID}查询主题为{selectedMainTopic}的场景查询结果: {theme_list}")
                return theme_list
            else:
                print("场景查询失败")
                return []
    except pymysql.MySQLError as err:
        print(f"场景查询异常: {err}")
        connection.rollback()
        return []
    finally:
        connection.close()



def getkoqathemeWithpermission(userID):
    connection = connect_to_db()
    if not connection:
        print("无法连接到数据库")
        return []
    try:
        with connection.cursor() as cursor:
            if not isadministrator(userID):
                cursor.execute(
                    "SELECT DISTINCT theme_name,topic_permission FROM ko_theme_permission where ("
                    "topic_permission='public' or create_id=%s) "
                    "AND theme_name IS NOT NULL AND theme_name != ''",
                    (userID,)
                )
            else:
                cursor.execute(
                    "SELECT DISTINCT theme_name,topic_permission  FROM ko_theme_permission WHERE theme_name IS NOT "
                    "NULL AND theme_name != '' "
                )
            result = cursor.fetchall()
            if result:
                # 将结果转换为列表形式
                theme_list = [[row[0],row[1]] for row in result]
                print(f"主题查询结果: {theme_list}")
                return theme_list
            else:
                print("主题查询失败")
                return []
    except pymysql.MySQLError as err:
        print(f"主题查询异常: {err}")
        connection.rollback()
        return []
    finally:
        connection.close()
