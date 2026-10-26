import unittest
from types import SimpleNamespace
from unittest.mock import patch

from vue_api.kdzn_hciqa.qa_answer.graph_stream_answer import data_generator
from vue_api.kdzn_hciqa.qa_answer.rag_stream_answer import generate_model_stream, stream_reasoning_answer
from vue_api.kdzn_hciqa.shared import get_model


def chunk(reasoning=None, content=None):
    return SimpleNamespace(choices=[SimpleNamespace(
        delta=SimpleNamespace(reasoning_content=reasoning, content=content), finish_reason=None
    )])


def date_response():
    return iter([
        chunk(reasoning="根据已有上下文回答。"),
        chunk(reasoning="直接回答日期。", content="今天是202"),
        chunk(content="6年10月22日，星期四。"),
    ])


class ReasoningStreamPrefixTests(unittest.TestCase):
    def test_mixed_delta_preserves_first_answer_and_last_reasoning(self):
        events = list(stream_reasoning_answer(date_response(), get_model("DeepSeekR1")))
        self.assertEqual("".join(delta for _, delta in events), "今天是2026年10月22日，星期四。")
        wire = "".join(event for event, _ in events)
        self.assertIn("直接回答日期。", wire)
        self.assertLess(wire.index("**开始回答：**"), wire.index("今天是202"))

    def test_direct_chat_history_contains_full_answer(self):
        state = SimpleNamespace(answer_content="")
        with patch("vue_api.kdzn_hciqa.qa_answer.rag_stream_answer.create_chat_stream", return_value=date_response()):
            events = list(generate_model_stream(state, True, get_model("DeepSeekR1"),
                          [{"role": "user", "content": "今天的日期是什么？"}], is_thinking=True))
        self.assertEqual(state.answer_content, "今天是2026年10月22日，星期四。")
        self.assertIn("data: 今天是202\n\n", "".join(events))

    def test_graph_chat_preserves_mixed_delta_answer(self):
        state = SimpleNamespace(answer_content="")
        client = SimpleNamespace(chat=SimpleNamespace(completions=SimpleNamespace(create=lambda **_: date_response())))
        with patch("vue_api.kdzn_hciqa.qa_answer.graph_stream_answer.get_llm_client_for_answer", return_value=client):
            events = list(data_generator("", state, True, get_model("DeepSeekR1"),
                          [{"role": "user", "content": "今天的日期是什么？"}], False, is_thinking=True))
        self.assertEqual(state.answer_content, "今天是2026年10月22日，星期四。")
        self.assertIn("data: 今天是202\n\n", "".join(events))


if __name__ == "__main__":
    unittest.main()
