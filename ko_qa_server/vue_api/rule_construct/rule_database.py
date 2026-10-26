import pymysql

from ..kdzn_hciqa.engine_dependencies.rule_vector_builder import (
    build_rule_entity_vector_store,
)


def get_label(conn, selectedMainScenario):
    """
    根据 theme_name 返回可能存在的多个 theme_label（去重）。
    不在这里关闭 conn，由调用方统一管理。
    """
    try:
        with conn.cursor() as cursor:
            sql = """
                SELECT DISTINCT theme_label
                FROM ko_theme_permission
                WHERE theme_name = %s
            """
            cursor.execute(sql, (selectedMainScenario,))
            rows = cursor.fetchall()  # e.g. (('a',), ('b',)) 或 [('a',), ('b',)]
            # 兼容不同返回格式
            labels = []
            for r in rows:
                # r 可能是元组或字典，统一取第一个字段
                if isinstance(r, (tuple, list)):
                    labels.append(r[0])
                elif isinstance(r, dict):
                    labels.append(r.get('theme_label'))
            # 去掉 None 和重复
            labels = [x for x in set(labels) if x]
            return labels
    except pymysql.MySQLError as err:
        print(f"权限/label 查询异常: {err}")
        return []


def get_label_with_userid(conn, selectedMainScenario, scene):
    # 直接通过 theme_name + scene_name 查询 theme_label
    try:
        with conn.cursor() as cursor:
            sql = """
                SELECT theme_label
                FROM ko_theme_permission
                WHERE theme_name = %s
                  AND scene_name  = %s
                LIMIT 1
            """
            cursor.execute(sql, (selectedMainScenario, scene))
            row = cursor.fetchone()
            return row[0] if row else None
    except pymysql.MySQLError as err:
        print(f"权限/label 查询异常: {err}")
        return None


def delete_records_by_rulename(connection, selectedMainScenario, rulename_list):
    if not rulename_list:
        print("未提供要删除的 rulename 列表")
        return
    try:
        with connection.cursor() as cursor:
            # 构建 IN 占位符
            in_placeholders = ','.join(['%s'] * len(rulename_list))

            if selectedMainScenario == '轨交诊断':
                delete_query = f"""
                    DELETE FROM ko_kdzn_rule_construct
                    WHERE rulename IN ({in_placeholders})
                    AND theme_label = 'kedazhineng'
                """
                params = rulename_list
            elif selectedMainScenario == '家谱问答':
                delete_query = f"""
                    DELETE FROM ko_kdzn_rule_construct
                    WHERE rulename IN ({in_placeholders})
                    AND theme_label = 'huaputong'
                """
                params = rulename_list
            else:
                delete_query = f"""
                    DELETE FROM ko_kdzn_rule_construct
                    WHERE rulename IN ({in_placeholders})
                      AND theme_name = %s
                """
                params = [*rulename_list, selectedMainScenario]

            cursor.execute(delete_query, params)
            connection.commit()
            print(f"成功删除 {cursor.rowcount} 条记录。")
    except pymysql.MySQLError as err:
        print(f"删除记录出错: {err}")
        connection.rollback()
    finally:
        connection.close()


def insert_new_data(connection, data_list, selectedMainScenario_label_with_ID, scene, selectedMainScenario):
    # 多个规则保存接口共用：保存规则记录，并尽量同步维护规则入口实体向量库。
    try:
        with connection.cursor() as cursor:
            insert_query = """
                INSERT INTO ko_kdzn_rule_construct (theme_name, theme_label, scene, rulename, rulepath, getin4simi, rulepath_human, getin4simi_human)
                VALUES (%s, %s, %s, %s, %s, %s, %s, %s)
            """
            insert_data = (
                selectedMainScenario, selectedMainScenario_label_with_ID, data_list[1], data_list[2], data_list[3],
                data_list[4], data_list[5], data_list[6]
            )
            cursor.execute(insert_query, insert_data)
            new_rid = cursor.lastrowid
            cursor.execute(
                """
                SELECT rid, theme_name, theme_label, rulename, getin4simi
                FROM ko_kdzn_rule_construct
                WHERE rid = %s
                """,
                (new_rid,),
            )
            row = cursor.fetchone()
            connection.commit()

        if selectedMainScenario != "家谱问答" and row:
            try:
                rule_row = {
                    "rid": row[0],
                    "theme_name": row[1],
                    "theme_label": row[2],
                    "rulename": row[3],
                    "getin4simi": row[4],
                }
                build_rule_entity_vector_store(rule_row)
            except Exception as exc:
                print(f"[rule_construct] 规则向量化失败，已跳过: {exc}")
        return True
    except pymysql.MySQLError as err:
        print(f"[rule_construct] 规则保存失败: {err}")
        try:
            connection.rollback()
        except Exception:
            pass
        return False
