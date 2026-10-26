import re
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



def modifi_data(connection, data_list):
    try:
        with connection.cursor() as cursor:
            update_query = """
                UPDATE ko_kdzn_rule_construct 
                SET scene = %s, rulename = %s, rulepath = %s, getin4simi = %s
                WHERE rid = %s
            """
            # Reorder data_list to match the query: scene, rulename, rulepath, getin4simi, rid
            cursor.execute(update_query, (data_list[1], data_list[2], data_list[3], data_list[4], data_list[0]))
            connection.commit()
            if cursor.rowcount > 0:
                print(f"Updated record with rid: {data_list[0]} for rulename: {data_list[2]}")
            else:
                print(f"No record found with rid: {data_list[0]} for rulename: {data_list[2]}")
    except pymysql.MySQLError as err:
        print(f"Error while updating data: {err}")
        connection.rollback()



def kdzn_file_rules_kdzn_generate(table_name, scene_choose):
    connection = connect_to_db()
    kdzn_file_rules_kdzn = {}
    jiapu_rule_list = {}
    if not connection:
        print("无法连接到数据库")
        return {}

    try:
        with connection.cursor(pymysql.cursors.DictCursor) as cursor:
            # 查询所有数据
            # query = "SELECT * FROM ko_kdzn_rule_construct"
            # table_name = "ko_kdzn_rule_construct_test"
            query = f"SELECT * FROM {table_name} WHERE theme_name= %s"
            cursor.execute(query, (scene_choose,))

            # 获取所有行
            results = cursor.fetchall()
            # 打印数据并构建字典
            if results:
                print(results)
                # print(f"{table_name}（label={label_with_ID}）表数据：")
                for row in results:
                    if scene_choose == "家谱问答":
                        rulename = row['rulename']
                        rule_data = {
                            "rid": row['rid'],
                            "rule_name": row['rulename'],
                            "rule_path": [row['rulepath']],  # 保持它是一个列表
                            "getIn4simi": row['getin4simi']
                        }

                        # 如果字典中已经存在该 scene，则追加数据
                        if rulename not in kdzn_file_rules_kdzn:
                            kdzn_file_rules_kdzn[rulename] = [rule_data]
                        else:
                            kdzn_file_rules_kdzn[rulename].append(rule_data)
                    else:
                        scene = row['scene']
                        rule_data = {
                            "rid": row['rid'],
                            "rule_name": row['rulename'],
                            "rule_path": [row['rulepath']],  # 保持它是一个列表
                            "getIn4simi": row['getin4simi']
                        }
                        # 如果字典中已经存在该 scene，则追加数据
                        if scene not in kdzn_file_rules_kdzn:
                            kdzn_file_rules_kdzn[scene] = [rule_data]
                        else:
                            kdzn_file_rules_kdzn[scene].append(rule_data)

            else:
                print("表中没有数据")

    except pymysql.MySQLError as err:
        print(f"查询错误: {err}")
        return {}
    finally:
        connection.close()  # 确保关闭连接

    return kdzn_file_rules_kdzn



def delpermission(data_list):
    """
    删除权限查询
    """
    koqatheme, scene, userID = data_list
    connection = connect_to_db()
    if not connection:
        print("无法连接到数据库")
        return False
    try:
        with connection.cursor() as cursor:
            if isadministrator(userID):
                return True
            cursor.execute(
                """select * from ko_theme_permission  
                where theme_name=%s AND scene_name=%s AND create_id=%s""",
                (koqatheme, scene, userID)
            )
            result = cursor.fetchone()
            if result:
                return True
            else:
                return False

    except pymysql.MySQLError as err:
        print(f"查询删除权限许可时发生错误: {err}")
        connection.rollback()
        return False
    finally:
        connection.close()


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


def insert_ko_theme_permission(theme_name, theme_des, theme_label, scene_name, create_id,
                               topic_perm, scene_perm, authorized_person, description):
    """
    插入数据直接调用这个
    """
    # 连接数据库（确保 connect_to_db 已正确实现并返回连接对象）
    connection = connect_to_db()
    if not connection:
        return False, 0  # 连接失败直接返回无权限

    try:
        with connection.cursor() as cursor:
            # SQL 语句使用参数化查询（已做到，避免注入）
            ins_sql = """
            INSERT INTO ko_theme_permission
            (theme_name, theme_des, theme_label, scene_name, create_id,
            topic_permission, scene_permission, authorized_person, description)
            VALUES(%s, %s, %s, %s, %s, %s, %s, %s, %s)
            """
            cursor.execute(
                ins_sql,
                (theme_name, theme_des, theme_label, scene_name, create_id,
                 topic_perm, scene_perm, authorized_person, description)
            )
            new_id = cursor.lastrowid
            connection.commit()
            return True, new_id

    except pymysql.MySQLError as e:
        print(f"数据库错误：{e}")  # 打印错误信息便于调试
        return False, 0  # 出错时默认无权限
    finally:
        connection.close()


def query_by_parentheses_chars(char1, char2, table='ko_kdzn_rule_construct', column='rulename'):
    """
    根据括号内的两个汉字（char1-char2）查询数据库中匹配的行。

    :param char1: 括号中第一个汉字，如 '彰'
    :param char2: 括号中第二个汉字，如 '德'
    :param table: 表名，默认 'generations'
    :param column: 字段名，默认 'name'
    :return: 匹配的记录列表，每条为字典
    """
    # 构造 LIKE 模式：%(彰-德)
    # 注意：MySQL 中 _ 和 % 是通配符，但汉字无冲突；为安全起见可不用转义
    db_config = {
        'host': cfg["KO_database"]["host"],
        'database': cfg["KO_database"]["database"],
        'user': cfg["KO_database"]["user"],
        'password': cfg["KO_database"]["password"],
        'charset': cfg["KO_database"]["charset"],
        'use_unicode': True,
        'connect_timeout': 10
    }
    pattern = f'%({char1}-{char2})'

    connection = None
    try:
        connection = pymysql.connect(**db_config)
        with connection.cursor(pymysql.cursors.DictCursor) as cursor:
            # 使用参数化查询防止注入（但 LIKE 模式需拼接，此处因输入为固定汉字，风险极低）
            # 更安全做法：验证 char1/char2 为单个汉字
            if not (re.fullmatch(r'\w', char1) and re.fullmatch(r'\w', char2)):
                raise ValueError("输入应为单个汉字或字母数字字符")

            sql = f"SELECT * FROM `{table}` WHERE `{column}` LIKE %s"
            cursor.execute(sql, (pattern,))
            results = cursor.fetchall()
            return list(results)

    except Exception as e:
        print(f"数据库查询出错: {e}")
        return []
    finally:
        if connection:
            connection.close()



def existence_by_topic_and_scene(theme_name, scene_name):
    # 连接数据库（确保 connect_to_db 已正确实现并返回连接对象）
    connection = connect_to_db()
    if not connection:
        return False  # 连接失败直接返回无权限

    try:
        with connection.cursor() as cursor:
            # SQL 语句使用参数化查询（已做到，避免注入）
            check_sql = """
            SELECT * FROM ko_theme_permission
            WHERE  theme_name=%s AND scene_name=%s
            """
            cursor.execute(check_sql, (theme_name, scene_name))
            result = cursor.fetchone()
            if result:
                return True
            else:
                return False

    except pymysql.MySQLError as e:
        print(f"数据库错误：{e}")  # 打印错误信息便于调试
        return False  # 出错时默认无权限
    finally:
        connection.close()



def upsert_theme_permission(theme_name, theme_label, scene_name,
                            create_id, topic_perm, scene_perm, description, theme_des):
    connection = connect_to_db()
    if not connection:
        return False, "无法连接到数据库", {}

    authorized_person = create_id
    # 若 topic_perm,scene_perm 为“假值”（None、空字符串、0 等），则赋值为 "private"
    topic_perm = topic_perm if topic_perm else "private"
    scene_perm = scene_perm if scene_perm else "private"

    try:
        with connection.cursor() as cursor:
            """
            因为在创建新场景下无法提供主题的描述信息，根据这个来分别请求（不想创建新的接口了）
            主题描述信息 
                1.空（创建场景）
                    判断场景是否存在 
                        a.存在 拒绝
                        b.不存在 获取描述

                2.不为空（创建主题和场景）
                判断场景是否存在
                    a.存在 拒绝
                    b.不存在 创建
            """
            if theme_des == "":
                if existence_by_topic_and_scene(theme_name, scene_name):
                    return False, "该场景已经存在", {}
                else:
                    # 注意：这里不再限定 scene_name / create_id，只要同一个 theme_name 之前存过，就拿来复用
                    fetch_des_sql = """
                                        SELECT theme_des
                                        FROM ko_theme_permission
                                        WHERE theme_name = %s
                                        ORDER BY id DESC
                                        LIMIT 1
                                    """
                    cursor.execute(fetch_des_sql, (theme_name,))
                    row_des = cursor.fetchone()
                    if row_des:
                        # row_des 是个 tuple，单列查询时下标 0
                        theme_des_candidate = row_des[0]
                        if theme_des_candidate:
                            theme_des = theme_des_candidate
                    result, new_id = insert_ko_theme_permission(theme_name, theme_des, theme_label, scene_name,
                                                                create_id, topic_perm, scene_perm,
                                                                authorized_person, description)
                    if result:
                        return True, None, {
                            "effect": "insert",
                            "id": new_id,
                            "theme_name": theme_name,
                            "scene_name": scene_name,
                        }
                    else:
                        return False, "数据添加失败", {}
            else:
                check_sql = """
                                SELECT * FROM ko_theme_permission
                                WHERE   theme_name=%s
                                """
                cursor.execute(check_sql, (theme_name,))
                result = cursor.fetchone()
                if result:
                    return False, "该主题已经存在", {}
                else:
                    result, new_id = insert_ko_theme_permission(theme_name, theme_des, theme_label, scene_name,
                                                                create_id, topic_perm, scene_perm,
                                                                authorized_person, description)
                    if result:
                        return True, None, {
                            "effect": "insert",
                            "id": new_id,
                            "theme_name": theme_name,
                            "scene_name": scene_name,
                        }
                    else:
                        return False, "数据添加失败", {}
    except pymysql.MySQLError as e:
        connection.rollback()
        return False, f"DB错误: {e}", {}
    finally:
        connection.close()



def has_permission_to_add(theme_name, scene_name, userID):
    """
    判断是否有权限添加数据
    格式6000971&6000707&6000901
    类似的
    """

    # 连接数据库（确保 connect_to_db 已正确实现并返回连接对象）
    connection = connect_to_db()
    if not connection:
        return False  # 连接失败直接返回无权限

    try:
        with connection.cursor() as cursor:
            # SQL 语句使用参数化查询（已做到，避免注入）
            permission_sql = """
            SELECT authorized_person FROM ko_theme_permission
            WHERE theme_name = %s AND scene_name = %s
            """
            cursor.execute(permission_sql, (theme_name, scene_name))
            result = cursor.fetchone()  # 获取一行结果
            if result:
                people = str(result[0])
                people_list = [p.strip() for p in people.split('&') if p.strip()]
                user_id_str = str(userID).strip()
                return user_id_str in people_list
            else:
                return False

    except pymysql.MySQLError as e:
        print(f"数据库错误：{e}")  # 打印错误信息便于调试
        return False  # 出错时默认无权限
    finally:
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




def deletekoqatheme(data_list):
    # data_list 现在包含: theme_name, theme_label, scene, userID
    theme_name, theme_label, scene, userID = data_list
    print(data_list)

    connection = connect_to_db()
    if not connection:
        print("无法连接到数据库")
        return False

    try:
        with connection.cursor() as cursor:
            # 仅删除该用户创建的对应授权记录
            delete_permission_sql = """
                DELETE FROM ko_theme_permission
                WHERE theme_name = %s
                  AND scene_name = %s
                  AND create_id = %s
            """
            cursor.execute(delete_permission_sql, (theme_name, scene, userID))
            permission_deleted = cursor.rowcount
            connection.commit()

            if permission_deleted > 0:
                print(f"成功删除 ko_theme_permission 中 {permission_deleted} 条记录: "
                      f"theme_name={theme_name}, scene={scene}, create_id={userID}")
            else:
                print(f"ko_theme_permission 中未找到记录或无权限删除: "
                      f"theme_name={theme_name}, scene={scene}, create_id={userID}")

            # 删除后，仅在该用户范围内检查是否还存在同 theme_label 的任意场景
            check_remaining_sql = """
                SELECT COUNT(*)
                FROM ko_theme_permission
                WHERE theme_label = %s
                  AND create_id = %s
            """
            cursor.execute(check_remaining_sql, (theme_label, userID))
            row = cursor.fetchone()
            remaining_cnt = row[0] if row else 0

            if remaining_cnt == 0:
                print(f"提示：该用户({userID})的 {theme_name} 主题下已经没有场景了（theme_label={theme_label}）。")

            return True

    except pymysql.MySQLError as err:
        print(f"删除数据时出错: {err}")
        connection.rollback()
        return False
    finally:
        connection.close()


if __name__ == '__main__':
    pass
