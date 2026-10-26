import unittest
from unittest.mock import patch

from fastapi.testclient import TestClient

from ko_qa_server import create_app
from vue_api.jiapu_qa.api import router as jiapu_router


class LegacyJiapuRouteTests(unittest.TestCase):
    def setUp(self):
        self.app = create_app()
        self.client = TestClient(self.app)
        self.addCleanup(self.client.close)

    def test_gateway_workflow_keeps_both_old_and_namespaced_routes(self):
        routes = {route.path: route for route in self.app.routes}
        for route in jiapu_router.routes:
            legacy_path = route.path[len(jiapu_router.prefix):]
            with self.subTest(path=legacy_path):
                legacy = routes[legacy_path]
                current = routes['/api' + route.path]
                self.assertIs(legacy.endpoint, current.endpoint)
                self.assertEqual(legacy.methods, current.methods)

    def test_old_intent_url_returns_the_same_response(self):
        for question in ('你好', '曾国藩的父亲是谁'):
            with self.subTest(question=question):
                old = self.client.post('/judgeYitu', json={'wenti': question})
                current = self.client.post('/api/jiapu_qa/judgeYitu', json={'wenti': question})
                self.assertEqual(old.status_code, 200)
                self.assertEqual(old.json()['response'], current.json()['response'])
                self.assertEqual(old.json()['status'], 200)

    def test_old_answer_url_preserves_sse_response(self):
        async def stream(history):
            self.assertEqual(history[-1]['content'], '你好')
            yield 'data: 你好\n\n'
            yield 'data: ，有什么可以帮助你？\n\n'

        with patch('vue_api.jiapu_qa.service.normal_answer_service.stream', new=stream):
            response = self.client.post('/normalAns', json={
                'history': '[{"role":"user","content":"你好"}]',
            })
        self.assertEqual(response.status_code, 200)
        self.assertIn('text/event-stream', response.headers['content-type'])
        self.assertEqual(response.text, 'data: 你好\n\ndata: ，有什么可以帮助你？\n\n')


if __name__ == '__main__':
    unittest.main()
