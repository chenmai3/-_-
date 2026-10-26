import unittest
from unittest.mock import AsyncMock, patch
from urllib.parse import parse_qs

import httpx

from vue_api.jiapu_qa.external_sources import (
    HuaPuTongClient, handle_hpt_answer, parse_mixed_json, parse_name_list,
)


class ExternalSourceParsingTests(unittest.TestCase):
    def test_parse_mixed_json_ignores_trailing_html(self):
        parsed = parse_mixed_json('{"flag":"1","ans":"ok"}<script>ignored</script>')
        self.assertEqual(parsed, {"flag": "1", "ans": "ok"})

    def test_parse_mixed_json_repairs_raw_newline_in_answer(self):
        parsed = parse_mixed_json('{"flag":"1","ans":"line1\nline2"}')
        self.assertEqual(parsed["ans"], "line1\nline2")

    def test_parse_name_list_accepts_json_string(self):
        self.assertEqual(parse_name_list('["曾国藩", "曾纪泽"]'), ["曾国藩", "曾纪泽"])


class HuaPuTongWorkflowTests(unittest.IsolatedAsyncioTestCase):
    async def test_submission_cookie_is_preserved_for_polling_and_users_are_isolated(self):
        task_count = 0

        def handle(request):
            nonlocal task_count
            if request.method == 'POST':
                self.assertNotIn('PHPSESSID', request.headers.get('cookie', ''))
                self.assertIn('Chrome/120', request.headers['user-agent'])
                form = parse_qs(request.content.decode())
                self.assertEqual(form['sign'], ['0'])
                self.assertEqual(form['myId'], ['["3030993"]'])
                task_count += 1
                return httpx.Response(200, json={'query_id': f'task-{task_count}'},
                    headers={'Set-Cookie': f'PHPSESSID=session-{task_count}; Path=/'})
            task = request.url.params['queryID'].split('-')[-1]
            self.assertIn(f'PHPSESSID=session-{task}', request.headers.get('cookie', ''))
            return httpx.Response(200, json={'flag': '1', 'ans': '外部家谱答案'})

        from vue_api.jiapu_qa.external_sources import HPT_HEADERS
        client = HuaPuTongClient()
        client._new_client = lambda: httpx.AsyncClient(
            transport=httpx.MockTransport(handle), headers=HPT_HEADERS,
        )
        for _ in range(2):
            _, answer = await client.ask({'sign': '0', 'myId': '["3030993"]'}, attempts=1)
            self.assertEqual(answer['ans'], '外部家谱答案')

    async def test_submit_reports_remote_parameter_validation_error(self):
        def handle(request):
            return httpx.Response(200, json={'detail': [
                {'loc': ['body', 'sign'], 'msg': 'Input should be a valid string'}
            ]})
        async with httpx.AsyncClient(transport=httpx.MockTransport(handle)) as session:
            with self.assertRaisesRegex(ValueError, 'sign.*Input should be a valid string'):
                await HuaPuTongClient().submit({}, client=session)

    async def test_waits_for_completion_and_keeps_remote_answer(self):
        client = HuaPuTongClient()
        client.submit = AsyncMock(return_value='test-task')
        answer = {'flag': '1', 'ans': '曾麟书', 'queries': [{'query': '父亲是谁'}]}
        client.get_result = AsyncMock(side_effect=[{'flag': '0', 'ans': ''}, answer])
        client.cancel = AsyncMock()
        with patch('vue_api.jiapu_qa.external_sources.asyncio.sleep', new=AsyncMock()):
            query_id, result = await client.ask({'data': 'test'}, attempts=2, interval=1)
        self.assertEqual((query_id, result), ('test-task', answer))
        client.cancel.assert_not_awaited()

    async def test_timeout_reports_unfinished_external_task_even_if_cleanup_fails(self):
        client = HuaPuTongClient()
        client.submit = AsyncMock(return_value='unfinished-task')
        client.get_result = AsyncMock(return_value={'flag': '0', 'ans': ''})
        client.cancel = AsyncMock(side_effect=RuntimeError('cleanup failed'))
        with self.assertRaisesRegex(TimeoutError, 'unfinished-task.*flag=0'):
            await client.ask({}, attempts=1)

    async def test_endpoint_keeps_names_and_surfaces_external_failure(self):
        with patch('vue_api.jiapu_qa.external_sources.hpt_client.ask', new=AsyncMock(
            return_value=('task', {'flag': '1', 'ans': '答案', 'name_list': ['曾国藩']})
        )):
            result = await handle_hpt_answer({})
        self.assertEqual(result['response']['name_list'], ['曾国藩'])
        with patch('vue_api.jiapu_qa.external_sources.hpt_client.ask', new=AsyncMock(
            side_effect=TimeoutError('外部服务仍为 flag=0')
        )):
            result = await handle_hpt_answer({})
        self.assertEqual(result['status'], 502)
        self.assertIn('flag=0', result['errorMessage'])
        self.assertFalse(result['response']['gotAns'])


if __name__ == "__main__":
    unittest.main()
