import unittest
from types import SimpleNamespace
from unittest.mock import patch

import httpx
from openai import NotFoundError

from vue_api.kdzn_hciqa.qa_answer.graph_stream_answer import data_generator
from vue_api.kdzn_hciqa.qa_answer.rag_stream_answer import generate_model_stream
from vue_api.kdzn_hciqa.shared import create_answer_stream_with_fallback, get_model


def model_not_found_error():
    request = httpx.Request("POST", "https://example.test/v1/chat/completions")
    response = httpx.Response(404, request=request)
    return NotFoundError(
        "Model not exist.", response=response, body={"code": "model_not_found"}
    )


def answer_chunk(text):
    return SimpleNamespace(
        choices=[SimpleNamespace(delta=SimpleNamespace(content=text))]
    )


def sensitive_chunk():
    return SimpleNamespace(
        choices=[SimpleNamespace(delta=SimpleNamespace(content=None), finish_reason="sensitive")]
    )


class AnswerModelFallbackTests(unittest.TestCase):
    def test_graph_answer_falls_back_after_deepseek_model_not_found(self):
        requested_model = get_model("DeepSeekR1")
        fallback_model = get_model("Qwen")
        called_models = []

        def make_client(_model):
            def create(**params):
                called_models.append(params["model"])
                if params["model"] == requested_model:
                    raise model_not_found_error()
                return iter([answer_chunk("检查连接部位。")])

            return SimpleNamespace(
                chat=SimpleNamespace(completions=SimpleNamespace(create=create))
            )

        state = SimpleNamespace(answer_content="")
        with patch(
            "vue_api.kdzn_hciqa.qa_answer.graph_stream_answer.get_llm_client_for_answer",
            side_effect=make_client,
        ):
            events = list(data_generator("", state, True, requested_model, [{"role": "user", "content": "问题"}], False))

        self.assertEqual(called_models, [requested_model, fallback_model])
        self.assertNotIn("已切换至", "".join(events))
        self.assertIn("检查连接部位。", "".join(events))
        self.assertNotIn("[ERROR]", "".join(events))
        self.assertEqual(state.answer_content, "检查连接部位。")

    def test_direct_answer_falls_back_after_deepseek_model_not_found(self):
        requested_model = get_model("DeepSeekV3")
        fallback_model = get_model("Qwen")
        called_models = []

        def create(model_name, _messages, is_thinking=False):
            called_models.append(model_name)
            if model_name == requested_model:
                raise model_not_found_error()
            return iter([answer_chunk("已回答")])

        state = SimpleNamespace(answer_content="")
        with patch(
            "vue_api.kdzn_hciqa.qa_answer.rag_stream_answer.create_chat_stream",
            side_effect=create,
        ):
            events = list(generate_model_stream(state, True, requested_model, [{"role": "user", "content": "问题"}]))

        self.assertEqual(called_models, [requested_model, fallback_model])
        self.assertNotIn("已切换至", "".join(events))
        self.assertIn("已回答", "".join(events))
        self.assertNotIn("[ERROR]", "".join(events))
        self.assertEqual(state.answer_content, "已回答")

    def test_other_errors_do_not_switch_model(self):
        called_models = []

        def create(model_name):
            called_models.append(model_name)
            raise RuntimeError("service unavailable")

        with self.assertRaisesRegex(RuntimeError, "service unavailable"):
            create_answer_stream_with_fallback(create, get_model("DeepSeekR1"))

        self.assertEqual(called_models, [get_model("DeepSeekR1")])

    def test_direct_answer_reports_sensitive_finish(self):
        state = SimpleNamespace(answer_content="")
        with patch(
            "vue_api.kdzn_hciqa.qa_answer.rag_stream_answer.create_chat_stream",
            return_value=iter([sensitive_chunk()]),
        ):
            events = list(generate_model_stream(state, True, get_model("ZhipuAI"), [{"role": "user", "content": "问题"}]))

        self.assertEqual(events, ["data: 抱歉，这个问题我不能回答\n\n"])
        self.assertEqual(state.answer_content, "抱歉，这个问题我不能回答")

    def test_direct_answer_reports_empty_stream(self):
        state = SimpleNamespace(answer_content="")
        with patch(
            "vue_api.kdzn_hciqa.qa_answer.rag_stream_answer.create_chat_stream",
            return_value=iter([]),
        ):
            events = list(generate_model_stream(state, True, get_model("ZhipuAI"), [{"role": "user", "content": "问题"}]))

        self.assertEqual(events, ["data: 模型未返回可显示的回答，请稍后重试。\n\n"])
        self.assertEqual(state.answer_content, "模型未返回可显示的回答，请稍后重试。")

    def test_graph_answer_reports_sensitive_finish(self):
        state = SimpleNamespace(answer_content="")
        client = SimpleNamespace(
            chat=SimpleNamespace(completions=SimpleNamespace(create=lambda **_: iter([sensitive_chunk()])))
        )
        with patch(
            "vue_api.kdzn_hciqa.qa_answer.graph_stream_answer.get_llm_client_for_answer",
            return_value=client,
        ):
            events = list(data_generator("", state, True, get_model("ZhipuAI"), [{"role": "user", "content": "问题"}], False))

        self.assertEqual(events, ["data: 抱歉，这个问题我不能回答\n\n"])
        self.assertEqual(state.answer_content, "抱歉，这个问题我不能回答")


if __name__ == "__main__":
    unittest.main()
