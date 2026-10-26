import unittest
from datetime import datetime, timezone
from unittest.mock import patch

from vue_api.kdzn_hciqa.qa_answer.prompt_security import current_time_context, prepare_qa_messages
from vue_api.kdzn_hciqa.qa_answer.rag_stream_answer import build_chat_params
from vue_api.kdzn_hciqa.engine_dependencies.llm_clients import gen_params
from vue_api.kdzn_hciqa.shared import get_model


class CurrentTimeTests(unittest.TestCase):
    def test_utc_clock_converts_to_beijing_next_day_and_weekday(self):
        context = current_time_context(datetime(2026, 10, 21, 17, 2, 3, tzinfo=timezone.utc))
        self.assertIn("2026年10月22日 01:02:03，星期四", context)
        self.assertIn("UTC+08:00", context)

    def test_each_request_refreshes_time_even_with_old_history(self):
        history = [
            {"role": "assistant", "content": "我无法获取实时日期。"},
            {"role": "user", "content": "今天的日期是什么？"},
        ]
        with patch("vue_api.kdzn_hciqa.qa_answer.prompt_security.current_time_context", side_effect=["当前时间一", "当前时间二"]):
            first = prepare_qa_messages(history)
            second = prepare_qa_messages(history)
        self.assertIn("当前时间一", first[0]["content"])
        self.assertIn("当前时间二", second[0]["content"])
        self.assertEqual(first[1:], history)
        self.assertEqual(len(history), 2)

    def test_all_direct_providers_receive_current_time(self):
        messages = [{"role": "user", "content": "今天的日期是什么？"}]
        for selection in ("DeepSeekV3", "DeepSeekR1", "Qwen", "Kimi", "ZhipuAI"):
            with self.subTest(selection=selection):
                params = build_chat_params({}, model_name=get_model(selection), messages=messages)
                self.assertIn("当前北京时间：", params["messages"][0]["content"])
        spark = gen_params("test_app", messages[0]["content"], "generalv3.5")
        self.assertIn("当前北京时间：", spark["payload"]["message"]["text"][0]["content"])


if __name__ == "__main__":
    unittest.main()
