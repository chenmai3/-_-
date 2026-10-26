from dataclasses import dataclass
from typing import Callable, Optional

from .common import connect_to_db, han2pinyin_concat


BUILTIN_THEME_LABELS = {
    "家谱问答": "huaputong",
    "轨交诊断": "kedazhineng",
}


def theme_label_for(theme_name: str, create_id: str) -> str:
    return BUILTIN_THEME_LABELS.get(theme_name, f"{han2pinyin_concat(theme_name)}_{create_id}")


def normalize_permission(value: Optional[str]) -> str:
    return value if value in {"public", "private"} else "private"


def authorized_people(value) -> set[str]:
    return {part.strip() for part in str(value or "").split("&") if part.strip()}


@dataclass
class ThemePermissionRepository:
    connection_factory: Callable = connect_to_db

    def _connect(self):
        connection = self.connection_factory()
        if connection is None:
            raise RuntimeError("数据库连接失败")
        return connection

    def _is_administrator(self, cursor, user_id: str) -> bool:
        cursor.execute(
            "SELECT 1 FROM koqa_administrator WHERE administrator=%s LIMIT 1",
            (user_id,),
        )
        return cursor.fetchone() is not None

    def list_themes(self, user_id: Optional[str] = None) -> list:
        connection = self._connect()
        try:
            with connection.cursor() as cursor:
                if user_id is None:
                    cursor.execute(
                        """SELECT DISTINCT theme_name
                           FROM ko_theme_permission
                           WHERE theme_name IS NOT NULL AND theme_name != ''
                           ORDER BY theme_name"""
                    )
                    return [row[0] for row in cursor.fetchall()]

                if self._is_administrator(cursor, user_id):
                    cursor.execute(
                        """SELECT DISTINCT theme_name, topic_permission
                           FROM ko_theme_permission
                           WHERE theme_name IS NOT NULL AND theme_name != ''
                           ORDER BY theme_name"""
                    )
                else:
                    cursor.execute(
                        """SELECT DISTINCT theme_name, topic_permission
                           FROM ko_theme_permission
                           WHERE (topic_permission='public' OR create_id=%s)
                             AND theme_name IS NOT NULL AND theme_name != ''
                           ORDER BY theme_name""",
                        (user_id,),
                    )
                return [[row[0], row[1]] for row in cursor.fetchall()]
        finally:
            connection.close()

    def list_scenarios(self, theme_name: str, user_id: Optional[str] = None) -> list[str]:
        connection = self._connect()
        try:
            with connection.cursor() as cursor:
                if user_id is None or self._is_administrator(cursor, user_id):
                    cursor.execute(
                        """SELECT DISTINCT scene_name
                           FROM ko_theme_permission
                           WHERE theme_name=%s
                             AND scene_name IS NOT NULL AND scene_name != ''
                           ORDER BY scene_name""",
                        (theme_name,),
                    )
                else:
                    cursor.execute(
                        """SELECT DISTINCT scene_name
                           FROM ko_theme_permission
                           WHERE theme_name=%s
                             AND (create_id=%s OR scene_permission='public')
                             AND scene_name IS NOT NULL AND scene_name != ''
                           ORDER BY scene_name""",
                        (theme_name, user_id),
                    )
                return [row[0] for row in cursor.fetchall()]
        finally:
            connection.close()

    def can_add(self, theme_name: str, scene_name: str, user_id: str) -> bool:
        connection = self._connect()
        try:
            with connection.cursor() as cursor:
                cursor.execute(
                    """SELECT authorized_person
                       FROM ko_theme_permission
                       WHERE theme_name=%s AND scene_name=%s
                       LIMIT 1""",
                    (theme_name, scene_name),
                )
                row = cursor.fetchone()
                return bool(row and str(user_id).strip() in authorized_people(row[0]))
        finally:
            connection.close()

    def can_delete(self, theme_name: str, scene_name: str, user_id: str) -> bool:
        connection = self._connect()
        try:
            with connection.cursor() as cursor:
                if self._is_administrator(cursor, user_id):
                    return True
                cursor.execute(
                    """SELECT 1 FROM ko_theme_permission
                       WHERE theme_name=%s AND scene_name=%s AND create_id=%s
                       LIMIT 1""",
                    (theme_name, scene_name, user_id),
                )
                return cursor.fetchone() is not None
        finally:
            connection.close()

    def create(self, payload: dict) -> tuple[bool, str, dict]:
        theme_name = str(payload.get("koqatheme") or "").strip()
        scene_name = str(payload.get("koqascenario") or "").strip()
        create_id = str(payload.get("createdID") or payload.get("userID") or "").strip()
        theme_description = str(payload.get("selectedMainScenario_description") or "").strip()
        scene_description = str(payload.get("scene_description") or payload.get("description") or "").strip()
        if not theme_name or not scene_name or not create_id:
            return False, "koqatheme、koqascenario、createdID 不能为空", {}

        connection = self._connect()
        try:
            with connection.cursor() as cursor:
                if theme_description:
                    cursor.execute(
                        "SELECT 1 FROM ko_theme_permission WHERE theme_name=%s LIMIT 1",
                        (theme_name,),
                    )
                    if cursor.fetchone():
                        return False, "该主题已经存在", {}
                else:
                    cursor.execute(
                        """SELECT 1 FROM ko_theme_permission
                           WHERE theme_name=%s AND scene_name=%s LIMIT 1""",
                        (theme_name, scene_name),
                    )
                    if cursor.fetchone():
                        return False, "该场景已经存在", {}
                    cursor.execute(
                        """SELECT theme_des FROM ko_theme_permission
                           WHERE theme_name=%s ORDER BY id DESC LIMIT 1""",
                        (theme_name,),
                    )
                    row = cursor.fetchone()
                    if row and row[0]:
                        theme_description = row[0]

                theme_label = theme_label_for(theme_name, create_id)
                cursor.execute(
                    """INSERT INTO ko_theme_permission
                       (theme_name, theme_des, theme_label, scene_name, create_id,
                        topic_permission, scene_permission, authorized_person, description)
                       VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s)""",
                    (
                        theme_name,
                        theme_description,
                        theme_label,
                        scene_name,
                        create_id,
                        normalize_permission(payload.get("topic_permission")),
                        normalize_permission(payload.get("scene_permission")),
                        create_id,
                        scene_description,
                    ),
                )
                new_id = cursor.lastrowid
            connection.commit()
            return True, "保存成功", {
                "effect": "insert",
                "id": new_id,
                "theme_name": theme_name,
                "scene_name": scene_name,
                "theme_label": theme_label,
            }
        except Exception:
            connection.rollback()
            raise
        finally:
            connection.close()

    def delete(self, theme_name: str, scene_name: str, user_id: str) -> bool:
        connection = self._connect()
        try:
            with connection.cursor() as cursor:
                cursor.execute(
                    """DELETE FROM ko_theme_permission
                       WHERE theme_name=%s AND scene_name=%s AND create_id=%s""",
                    (theme_name, scene_name, user_id),
                )
            connection.commit()
            return True
        except Exception:
            connection.rollback()
            raise
        finally:
            connection.close()
