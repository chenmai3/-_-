import unittest
import json
from unittest.mock import MagicMock, patch

from fastapi.testclient import TestClient
from ko_qa_server import create_app

from vue_api.kdzn_hciqa.conversation_history.delete_conversation import (
    handle_delete_conversation_by_id,
)


class FakeRequest:
    async def json(self):
        return {"qid": "conversation-1", "userId": "user-1"}


class ConversationHistoryTests(unittest.IsolatedAsyncioTestCase):
    @patch(
        "vue_api.kdzn_hciqa.conversation_history.delete_conversation."
        "general_query_states"
    )
    @patch(
        "vue_api.kdzn_hciqa.conversation_history.delete_conversation."
        "family_relation_states"
    )
    @patch(
        "vue_api.kdzn_hciqa.conversation_history.delete_conversation."
        "connect_to_db"
    )
    async def test_delete_conversation_clears_query_states(
        self,
        connect,
        family_states,
        general_states,
    ):
        connection = MagicMock()
        connect.return_value = connection

        response = await handle_delete_conversation_by_id(FakeRequest())

        self.assertEqual(response.status_code, 200)
        connection.commit.assert_called_once_with()
        family_states.clear.assert_called_once_with("conversation-1")
        general_states.clear.assert_called_once_with("conversation-1")
        connection.close.assert_called_once_with()


class ConversationDetailTests(unittest.TestCase):
    module = 'vue_api.kdzn_hciqa.conversation_history.get_conversation_detail'

    def connection_for(self, row):
        connection = MagicMock()
        connection.cursor.return_value.__enter__.return_value.fetchone.return_value = row
        return connection

    def test_legacy_and_current_routes_return_saved_history(self):
        turns = [{'query': '曾国藩的儿子是谁？', 'answer': '曾纪泽、曾纪鸿', 'scene': '家谱问答'}]
        for saved in (json.dumps(turns, ensure_ascii=False), str(turns), turns[0]):
            with self.subTest(saved_type=type(saved).__name__):
                connection = self.connection_for({'title': '家谱查询', 'history_qa': saved})
                with patch(self.module + '.connect_to_db', return_value=connection):
                    with TestClient(create_app()) as client:
                        for route in ('/get_conversations', '/api/kdzn_qa/get_conversations'):
                            response = client.post(route, json={'qid': 'existing-history'})
                            self.assertEqual(response.status_code, 200)
                            self.assertEqual(response.json(), {'q_history': turns})
                connection.cursor.return_value.__enter__.return_value.execute.assert_called_with(
                    unittest.mock.ANY, ('existing-history',),
                )
                self.assertTrue(connection.close.called)

    def test_missing_id_does_not_query_database(self):
        with patch(self.module + '.connect_to_db') as connect:
            with TestClient(create_app()) as client:
                for body in ({}, {'qid': ''}, {'qid': []}, []):
                    self.assertEqual(client.post('/get_conversations', json=body).status_code, 400)
        connect.assert_not_called()

    def test_database_failure_does_not_return_a_successful_empty_history(self):
        with patch(self.module + '.connect_to_db', return_value=None):
            with TestClient(create_app()) as client:
                response = client.post('/get_conversations', json={'qid': 'existing-history'})
        self.assertEqual(response.status_code, 503)
        self.assertIn('数据库连接失败', response.json()['message'])

    def test_missing_or_malformed_history_returns_an_explicit_error(self):
        for row, status in ((None, 404), ({'title': '查询', 'history_qa': 'broken data'}, 500)):
            connection = self.connection_for(row)
            with patch(self.module + '.connect_to_db', return_value=connection):
                with TestClient(create_app()) as client:
                    response = client.post('/get_conversations', json={'qid': 'missing-history'})
            self.assertEqual(response.status_code, status)
            self.assertIn('message', response.json())
            connection.close.assert_called_once_with()

    def test_unanswered_history_keeps_the_saved_question_visible(self):
        connection = self.connection_for({'title': '未完成的问题', 'history_qa': None})
        with patch(self.module + '.connect_to_db', return_value=connection):
            with TestClient(create_app()) as client:
                response = client.post('/get_conversations', json={'qid': 'unfinished-history'})
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()['q_history'][0]['query'], '未完成的问题')


if __name__ == "__main__":
    unittest.main()
