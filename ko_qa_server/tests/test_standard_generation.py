import json
import os
import queue
import unittest
from types import SimpleNamespace
from unittest.mock import Mock, patch

from fastapi.testclient import TestClient
from ko_qa_server import create_app
from vue_api.kdzn_hciqa.standard_document.generate_standard_document import (
    run_standard_generation, standard_queue_consumer,
)
from vue_api.kdzn_hciqa.standard_document.generation_engine.qwen80b_chat import (
    get_standard_llm_config, run_stage_with_progress,
)
from vue_api.kdzn_hciqa.standard_document.request_intent import classify_standard_request
from vue_api.kdzn_hciqa.qa_answer.rag_stream_answer import direct_qa_history


class StandardGenerationTests(unittest.TestCase):
    def test_config_uses_model_from_the_same_provider_as_credentials(self):
        with patch.dict(os.environ, {}, clear=True), patch(
            'vue_api.kdzn_hciqa.standard_document.generation_engine.qwen80b_chat.load_config',
            return_value={'small_models': {'qwen': {'qwen2.5_model_name': 'qwen-max'}}},
        ):
            self.assertEqual(get_standard_llm_config()['model'], 'qwen-max')
            with patch.dict(os.environ, {'STANDARD_DOC_LLM_MODEL': 'my-local-model'}):
                self.assertEqual(get_standard_llm_config()['model'], 'my-local-model')

    def test_all_gateway_routes_preserve_structured_events(self):
        def fake_generation(query, state, events):
            self.assertEqual(query, '生成标准')
            events.put('data: {"section":"qianyan","content":"前言正文"}\n\n')
            events.put(None)

        with patch('vue_api.kdzn_hciqa.standard_document.generate_standard_document.run_standard_generation', fake_generation), patch(
            'vue_api.kdzn_hciqa.standard_document.generate_standard_document.classify_standard_request', return_value='standard',
        ):
            with TestClient(create_app()) as client:
                for path in ('/api/kdzn_qa/gen_biaozhun', '/gen_biaozhun', '/zhongshaoxuan/test'):
                    with self.subTest(path=path):
                        response = client.post(path, json={'input': '生成标准'})
                        self.assertEqual(response.status_code, 200)
                        self.assertIn('text/event-stream', response.headers['content-type'])
                        self.assertIn('no-transform', response.headers['cache-control'])
                        frames = [json.loads(frame[6:]) for frame in response.text.strip().split('\n\n')]
                        self.assertEqual(frames[0], {'section': 'judge', 'content': 'standard'})
                        self.assertEqual(frames[1]['content'], '前言正文')

    def test_intent_reuses_chunfeng_recognition_and_chitchat_decision(self):
        from vue_api.kdzn_hciqa.engine_dependencies.prompt_builders import prompt_list
        for is_chat in (True, False):
            with self.subTest(is_chat=is_chat):
                engine = Mock(prompt_list=prompt_list)
                intent = SimpleNamespace(yitu='Chitchat' if is_chat else 'General Query')
                engine.recognize_intent.return_value = intent
                engine.is_chitchat_turn.return_value = is_chat
                with patch('vue_api.kdzn_hciqa.standard_document.request_intent.get_kdzn_engine', return_value=engine):
                    actual = classify_standard_request('用户输入')
                self.assertEqual(actual, 'chat' if is_chat else 'standard')
                question, prompt = engine.recognize_intent.call_args_list[0].args
                self.assertEqual(question, '用户输入')
                self.assertIn('标准生成', prompt)
                self.assertNotIn('__input__', prompt)
                self.assertNotIn('__domain_desc__', prompt)
                engine.is_chitchat_turn.assert_called_once_with('标准生成', intent, '')
                self.assertEqual(engine.recognize_intent.call_count, 2 if is_chat else 1)

    def test_genealogy_uses_existing_family_prompt_after_standard_classification(self):
        from vue_api.kdzn_hciqa.engine_dependencies.prompt_builders import prompt_list
        query = '曾国藩的儿子的父亲的爷爷的孙子的重孙是谁？'
        engine = Mock(prompt_list=prompt_list)
        engine.recognize_intent.side_effect = [
            SimpleNamespace(yitu='Chitchat'), SimpleNamespace(yitu='jiapu Query'),
        ]
        engine.is_chitchat_turn.return_value = True
        with patch('vue_api.kdzn_hciqa.standard_document.request_intent.get_kdzn_engine', return_value=engine):
            self.assertEqual(classify_standard_request(query), 'family')
        engine.recognize_intent.assert_called_with(
            query, prompt_list['jiapu_general_yitu_file'].replace('__input__', query),
        )

    def test_genealogy_document_request_keeps_standard_generation_priority(self):
        from vue_api.kdzn_hciqa.engine_dependencies.prompt_builders import prompt_list
        engine = Mock(prompt_list=prompt_list)
        engine.recognize_intent.return_value = SimpleNamespace(yitu='General Query')
        engine.is_chitchat_turn.return_value = False
        with patch('vue_api.kdzn_hciqa.standard_document.request_intent.get_kdzn_engine', return_value=engine):
            self.assertEqual(classify_standard_request('帮我编写家谱数据管理标准'), 'standard')
        self.assertEqual(engine.recognize_intent.call_count, 1)

    def test_family_questions_show_switch_notice_without_generating_an_answer(self):
        with patch('vue_api.kdzn_hciqa.standard_document.generate_standard_document.classify_standard_request', return_value='family'), patch(
            'vue_api.kdzn_hciqa.standard_document.generate_standard_document.run_standard_generation',
        ) as document, patch(
            'vue_api.kdzn_hciqa.standard_document.generate_standard_document.start_direct_question_worker',
        ) as direct:
            with TestClient(create_app()) as client:
                for model in ('DeepSeekV3', 'Qwen', 'Kimi', 'Spark', 'ZhipuAI'):
                    with self.subTest(model=model):
                        response = client.post('/api/kdzn_qa/gen_biaozhun', json={
                            'query': '曾国藩的儿子的父亲的爷爷的孙子的重孙是谁？',
                            'model_choose': model, 'qid': 'family-switch-' + model,
                        })
                        self.assertEqual(response.status_code, 200)
                        frames = [json.loads(frame[6:]) for frame in response.text.strip().split('\n\n')]
                        self.assertEqual(frames, [
                            {'section': 'judge', 'content': 'family'},
                            {'section': 'notice', 'content': '该问题属于家谱关系查询，请切换到“家谱问答”后提问。'},
                        ])
                        self.assertFalse(direct_qa_history.get_user_qa_history('standard-chat:family-switch-' + model))
        document.assert_not_called()
        direct.assert_not_called()

    def test_chitchat_calls_the_selected_model_and_never_starts_document_generation(self):
        from vue_api.kdzn_hciqa.shared import get_model
        for selection in ('DeepSeekV3', 'DeepSeekR1', 'Qwen', 'Kimi', 'Spark', 'ZhipuAI'):
            with self.subTest(model=selection):
                def answer(state, web, model, messages, **kwargs):
                    self.assertEqual(model, get_model(selection))
                    self.assertEqual(messages[-1], {'role': 'user', 'content': '你好'})
                    state.answer_content = '你好，有什么可以帮您？'
                    yield 'data: 你好，\n\n'
                    yield 'data: 有什么可以帮您？\n\n'

                with patch('vue_api.kdzn_hciqa.standard_document.generate_standard_document.classify_standard_request', return_value='chat'), patch(
                    'vue_api.kdzn_hciqa.standard_document.generate_standard_document.run_standard_generation',
                ) as document, patch(
                    'vue_api.kdzn_hciqa.qa_answer.rag_stream_answer.generate_model_stream', side_effect=answer,
                ):
                    with TestClient(create_app()) as client:
                        response = client.post('/api/kdzn_qa/gen_biaozhun', json={
                            'query': '你好', 'qid': 'chat-route-' + selection, 'model_choose': selection,
                        })
                self.assertEqual(response.status_code, 200)
                self.assertIn('"content": "chat"', response.text)
                self.assertIn('data: 你好，\n\ndata: 有什么可以帮您？\n\n', response.text)
                self.assertNotIn('qianyan', response.text)
                document.assert_not_called()

    def test_chat_reuses_history_from_this_entry_only(self):
        history_id = 'standard-chat:test-standard-history'
        direct_qa_history.add_or_update_user_qa(history_id, [
            {'role': 'user', 'content': '我叫小王'}, {'role': 'assistant', 'content': '你好小王'},
        ])
        def answer(state, web, model, messages, **kwargs):
            self.assertEqual(messages[0]['content'], '我叫小王')
            self.assertEqual(messages[-1]['content'], '我叫什么？')
            state.answer_content = '小王'
            yield 'data: 小王\n\n'

        with patch('vue_api.kdzn_hciqa.standard_document.generate_standard_document.classify_standard_request', return_value='chat'), patch(
            'vue_api.kdzn_hciqa.qa_answer.rag_stream_answer.generate_model_stream', side_effect=answer,
        ):
            with TestClient(create_app()) as client:
                response = client.post('/api/kdzn_qa/gen_biaozhun', json={
                    'query': '我叫什么？', 'qid': 'test-standard-history', 'model_choose': 'Qwen',
                })
        self.assertIn('data: 小王', response.text)

    def test_intent_failure_finishes_with_a_visible_error(self):
        with patch('vue_api.kdzn_hciqa.standard_document.generate_standard_document.classify_standard_request', side_effect=RuntimeError('network unavailable')), patch(
            'vue_api.kdzn_hciqa.standard_document.generate_standard_document.run_standard_generation',
        ) as document:
            with TestClient(create_app()) as client:
                response = client.post('/api/kdzn_qa/gen_biaozhun', json={'query': '你好'})
        self.assertIn('event: error', response.text)
        document.assert_not_called()

    def test_invalid_questions_do_not_start_intent_or_document_calls(self):
        with patch('vue_api.kdzn_hciqa.standard_document.generate_standard_document.classify_standard_request') as classify:
            with TestClient(create_app()) as client:
                for payload in ({'query': '  '}, {'query': 123}, []):
                    self.assertEqual(client.post('/api/kdzn_qa/gen_biaozhun', json=payload).status_code, 400)
        classify.assert_not_called()

    def test_worker_failure_emits_error_and_closes_the_queue(self):
        # Import here so the normal route tests do not load embedding dependencies.
        with patch('vue_api.kdzn_hciqa.standard_document.generation_engine.server.generate_content', side_effect=RuntimeError('test failure')):
            events = queue.Queue()
            run_standard_generation('生成标准', SimpleNamespace(), events)
            frames = list(standard_queue_consumer(events, timeout=1))
        self.assertEqual(len(frames), 1)
        self.assertTrue(frames[0].startswith('event: error\n'))
        self.assertIn('标准生成失败', frames[0])

    def test_failed_background_stage_exits_instead_of_hanging(self):
        with patch('vue_api.kdzn_hciqa.standard_document.generation_engine.qwen80b_chat.chat_async', side_effect=RuntimeError('model unavailable')):
            with self.assertRaisesRegex(RuntimeError, 'model unavailable'):
                list(run_stage_with_progress([[{'role': 'user', 'content': 'test'}]], '正文', 'dagang'))

    def test_section_slicing_preserves_whitespace_and_never_splits_placeholders(self):
        from vue_api.kdzn_hciqa.standard_document.generation_engine.server import stream_section
        text = '# 正文\n\n术语 A\n下一段'
        chunks = [json.loads(frame[6:]) for frame in stream_section('zhengwen', text, chunk_size=3)]
        self.assertEqual(''.join(chunk['content'] for chunk in chunks), text)
        self.assertTrue(all(chunk['section'] == 'zhengwen' for chunk in chunks))


if __name__ == '__main__':
    unittest.main()
