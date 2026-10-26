import unittest
from types import SimpleNamespace

from vue_api.kdzn_hciqa.engine_dependencies.llm_clients import (
    call_qwen_messages,
    cfg,
)


class LlmClientTests(unittest.TestCase):
    def test_qwen_message_helper_uses_requested_model(self):
        calls = []

        def create(**kwargs):
            calls.append(kwargs)
            return SimpleNamespace(
                choices=[SimpleNamespace(message=SimpleNamespace(content="answer"))]
            )

        client = SimpleNamespace(
            chat=SimpleNamespace(completions=SimpleNamespace(create=create))
        )
        answer = call_qwen_messages(
            [{"role": "user", "content": "question"}],
            model_name="qwen2.5",
            client=client,
        )

        self.assertEqual(answer, "answer")
        self.assertEqual(
            calls[0]["model"],
            cfg["small_models"]["qwen"]["qwen2.5_model_name"],
        )

    def test_qwen_message_helper_handles_ordinary_errors(self):
        def create(**kwargs):
            raise RuntimeError("offline")

        client = SimpleNamespace(
            chat=SimpleNamespace(completions=SimpleNamespace(create=create))
        )

        self.assertIsNone(call_qwen_messages([], client=client))


if __name__ == "__main__":
    unittest.main()
