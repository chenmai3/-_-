import unittest

from vue_api.common.server_settings import load_server_settings


class ServerSettingsTests(unittest.TestCase):
    def test_defaults_are_production_safe(self):
        settings = load_server_settings({})

        self.assertEqual(settings.host, "0.0.0.0")
        self.assertEqual(settings.port, 8998)
        self.assertFalse(settings.debug)
        self.assertFalse(settings.reload)

    def test_environment_overrides_server_settings(self):
        settings = load_server_settings(
            {
                "KO_QA_HOST": "127.0.0.1",
                "KO_QA_PORT": "9001",
                "KO_QA_DEBUG": "yes",
                "KO_QA_RELOAD": "1",
            }
        )

        self.assertEqual(settings.host, "127.0.0.1")
        self.assertEqual(settings.port, 9001)
        self.assertTrue(settings.debug)
        self.assertTrue(settings.reload)

    def test_invalid_boolean_is_rejected(self):
        with self.assertRaises(ValueError):
            load_server_settings({"KO_QA_DEBUG": "sometimes"})

    def test_invalid_port_is_rejected(self):
        for value in ("0", "65536", "not-a-port"):
            with self.subTest(value=value), self.assertRaises(ValueError):
                load_server_settings({"KO_QA_PORT": value})


if __name__ == "__main__":
    unittest.main()
