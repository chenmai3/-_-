import unittest

from vue_api.rule_construct.theme_repository import (
    authorized_people,
    normalize_permission,
    theme_label_for,
)


class ThemeRepositoryHelpersTests(unittest.TestCase):
    def test_builtin_theme_labels_remain_stable(self):
        self.assertEqual(theme_label_for("轨交诊断", "6000971"), "kedazhineng")
        self.assertEqual(theme_label_for("家谱问答", "6000971"), "huaputong")

    def test_custom_theme_label_is_scoped_to_creator(self):
        self.assertEqual(theme_label_for("设备检修", "6000971"), "shebeijianxiu_6000971")

    def test_invalid_permission_defaults_to_private(self):
        self.assertEqual(normalize_permission("public"), "public")
        self.assertEqual(normalize_permission("private"), "private")
        self.assertEqual(normalize_permission(""), "private")
        self.assertEqual(normalize_permission("unexpected"), "private")

    def test_authorized_people_parses_ampersand_list(self):
        self.assertEqual(
            authorized_people("6000971& 6000750 &&6000901"),
            {"6000971", "6000750", "6000901"},
        )


if __name__ == "__main__":
    unittest.main()
