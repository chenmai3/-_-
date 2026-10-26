import unittest

from vue_api.kdzn_hciqa.shared import Result, get_model, load_config


class ResultModelTests(unittest.TestCase):
    def test_result_accepts_none_error_message(self):
        response = Result(response={"ok": True}, errorMessage=None)

        self.assertEqual(response.status, 200)
        self.assertIsNone(response.errorMessage)
        self.assertEqual(response.response, {"ok": True})

    def test_qwen_choice_uses_current_configured_model(self):
        self.assertEqual(
            get_model("Qwen"),
            load_config()["small_models"]["qwen"]["qwen2_model_name"],
        )


if __name__ == "__main__":
    unittest.main()
