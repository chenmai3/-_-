import json
import unittest
from types import SimpleNamespace
from unittest.mock import Mock, patch

from vue_api.kdzn_hciqa.engine_dependencies.llm_clients import Ws_Param, llm_config


class SparkTransportTests(unittest.TestCase):
    def stream(self, url="wss://spark-api.xf-yun.com/v3.5/chat"):
        client = llm_config.__new__(llm_config)
        return client.spark("test-app", "test-key", "test-secret", url,
                            "generalv3.5", "变压器如何检修？", timeout=1)

    def test_websocket_signer_rejects_http_endpoint(self):
        with patch("vue_api.kdzn_hciqa.engine_dependencies.llm_clients.websocket.WebSocketApp") as factory:
            with self.assertRaisesRegex(ValueError, "WebSocket 地址"):
                Ws_Param("app", "key", "secret", "https://spark-api-open.xf-yun.com/v1")
            factory.assert_not_called()

    def test_http_configuration_streams_without_using_websocket(self):
        client = Mock()
        events = iter([
            SimpleNamespace(choices=[SimpleNamespace(delta=SimpleNamespace(content="## 检修\n"), finish_reason=None)]),
            SimpleNamespace(choices=[SimpleNamespace(delta=SimpleNamespace(content="1. 断电"), finish_reason=None)]),
        ])
        client.chat.completions.create.return_value.__enter__ = Mock(return_value=events)
        client.chat.completions.create.return_value.__exit__ = Mock(return_value=False)
        manager = Mock(__enter__=Mock(return_value=client), __exit__=Mock(return_value=False))
        with patch("vue_api.kdzn_hciqa.engine_dependencies.llm_clients.OpenAI", return_value=manager) as factory, patch(
            "vue_api.kdzn_hciqa.engine_dependencies.llm_clients.websocket.WebSocketApp"
        ) as websocket_factory:
            generator = self.stream("https://spark-api-open.xf-yun.com/v1")
            self.assertEqual(next(generator), "## 检修\n")
            self.assertEqual(list(generator), ["1. 断电"])
            factory.assert_called_once_with(api_key="test-key", base_url="https://spark-api-open.xf-yun.com/v1", timeout=1, max_retries=0)
            params = client.chat.completions.create.call_args.kwargs
            self.assertEqual(params["model"], "generalv3.5")
            self.assertTrue(params["stream"])
            self.assertEqual(params["messages"][0]["role"], "system")
            websocket_factory.assert_not_called()

    def test_signed_url_uses_websocket_endpoint(self):
        param = Ws_Param("app", "key", "secret", "wss://spark-api.xf-yun.com/v3.5/chat")
        self.assertTrue(param.create_url().startswith("wss://spark-api.xf-yun.com/v3.5/chat?"))
        self.assertEqual(param.host, "spark-api.xf-yun.com")
        self.assertEqual(param.path, "/v3.5/chat")

    def test_worker_startup_error_is_propagated_instead_of_timeout(self):
        ws = Mock()
        ws.run_forever.side_effect = ValueError("connection startup failed")
        with patch("vue_api.kdzn_hciqa.engine_dependencies.llm_clients.websocket.WebSocketApp", return_value=ws):
            with self.assertRaisesRegex(ValueError, "connection startup failed"):
                list(self.stream())
        ws.close.assert_called()

    def test_deltas_are_available_before_final_event(self):
        import threading
        first_sent = threading.Event()
        finish = threading.Event()
        ws = Mock()

        def factory(url, **callbacks):
            def run(**kwargs):
                callbacks["on_open"](ws)
                callbacks["on_message"](ws, json.dumps({
                    "header": {"code": 0},
                    "payload": {"choices": {"status": 1, "text": [{"content": "## 检修\n"}]}},
                }))
                first_sent.set()
                finish.wait(2)
                callbacks["on_message"](ws, json.dumps({
                    "header": {"code": 0},
                    "payload": {"choices": {"status": 2, "text": [{"content": "1. 断电"}]}},
                }))
                callbacks["on_close"](ws, 1000, "")
            ws.run_forever.side_effect = run
            return ws

        with patch("vue_api.kdzn_hciqa.engine_dependencies.llm_clients.websocket.WebSocketApp", side_effect=factory):
            stream = self.stream()
            try:
                self.assertEqual(next(stream), "## 检修\n")
                self.assertTrue(first_sent.wait(1))
                self.assertFalse(finish.is_set())
                finish.set()
                self.assertEqual(list(stream), ["1. 断电"])
            finally:
                finish.set()
                stream.close()
        ws.close.assert_called()

    def test_premature_close_reports_connection_error(self):
        ws = Mock()

        def factory(url, **callbacks):
            ws.run_forever.side_effect = lambda **kwargs: callbacks["on_close"](ws, 1006, "")
            return ws

        with patch("vue_api.kdzn_hciqa.engine_dependencies.llm_clients.websocket.WebSocketApp", side_effect=factory):
            with self.assertRaisesRegex(ConnectionError, "回答完成前关闭"):
                list(self.stream())


if __name__ == "__main__":
    unittest.main()
