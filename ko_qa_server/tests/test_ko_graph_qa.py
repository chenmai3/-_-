import json
import unittest
from unittest.mock import patch

from fastapi.testclient import TestClient

from ko_qa_server import create_app
from vue_api.jiapu_qa.ko_graph import extract_entities, retrieve_graph

MODULE = 'vue_api.jiapu_qa.ko_graph'


class KoGraphQaTests(unittest.TestCase):
    def test_relationship_question_uses_both_entities_without_family_scene(self):
        self.assertEqual(extract_entities('吴信东和原子弹是什么关系？', []), ['吴信东', '原子弹'])

    @patch(MODULE + '.query_new_neo4j')
    def test_queries_legacy_ownthink_graph_with_bound_entity_parameters(self, query):
        query.side_effect = [
            [{'name': '吴信东', 'properties': {'name': '吴信东'}},
             {'name': '原子弹', 'properties': {'name': '原子弹'}}],
            [], [], [],
        ]
        evidence = retrieve_graph(['吴信东', '原子弹'])
        self.assertEqual(len(evidence['entities']), 2)
        self.assertIn('ownthink', query.call_args_list[0].args[0])
        self.assertIn('shortestPath', query.call_args_list[1].args[0])
        self.assertNotIn('吴信东', query.call_args_list[1].args[0])
        self.assertEqual(query.call_args_list[1].kwargs['parameters'], {'head': '吴信东', 'tail': '原子弹'})
        self.assertTrue(all(call.kwargs['kg'] == 'jiapu' for call in query.call_args_list))

    def test_stream_keeps_paths_separate_and_grounds_answer_in_remote_graph(self):
        evidence = {'entities': [{'name': '吴信东', 'properties': {'研究方向': '人工智能'}}],
                    'paths': ['吴信东-研究方向->人工智能-相关->原子弹']}

        def answer(state, web, model, messages, **kwargs):
            self.assertIn(evidence['paths'][0], messages[-1]['content'])
            self.assertNotIn('曾国藩', messages[-1]['content'])
            self.assertNotIn('PrOSpLiT', messages[-1]['content'])
            yield 'data: 根据检索路径，两者存在间接关联。\n\n'

        with patch(MODULE + '.retrieve_graph', return_value=evidence), \
             patch(MODULE + '.generate_model_stream', side_effect=answer), \
             patch(MODULE + '.get_model', return_value='test-model'), TestClient(create_app()) as client:
            response = client.post('/ko_kg_mul_qa_stream', json={
                'qid': 'ko-regression', 'model_choose': 'DeepSeekV3',
                'u_input': json.dumps([{'role': 'user', 'content': '吴信东和原子弹是什么关系？'}]),
            })
        self.assertEqual(response.status_code, 200)
        self.assertIn('text/event-stream', response.headers['content-type'])
        self.assertIn('"type": "paths"', response.text)
        self.assertIn(evidence['paths'][0], response.text)
        self.assertIn('根据检索路径，两者存在间接关联。', response.text)
        self.assertNotIn('PrOSpLiT', response.text)

    def test_graph_connection_failure_surfaces_as_error_without_general_model_answer(self):
        with patch(MODULE + '.retrieve_graph', side_effect=RuntimeError('connection unavailable')), \
             patch(MODULE + '.generate_model_stream') as answer, TestClient(create_app()) as client:
            response = client.post('/ko_kg_mul_qa_stream', json={
                'query': '吴信东和原子弹是什么关系？', 'qid': 'failed-graph',
            })
        self.assertIn('"error"', response.text)
        answer.assert_not_called()


if __name__ == '__main__':
    unittest.main()
