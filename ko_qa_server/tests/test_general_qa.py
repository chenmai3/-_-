import unittest

from vue_api.general_qa.service import (
    GeneralQaService,
    extract_web_text,
    knowledge_base_assets_exist,
    validate_public_http_url,
)


class FakeLlm:
    def __init__(self):
        self.prompt = ""

    def qwen2(self, _head, prompt):
        self.prompt = prompt
        return "测试答案"


class FakeChatbot:
    def koquery2kb(self, prompt, user_id):
        return f"KB[{user_id}]:{prompt}"


class GeneralQaHelpersTests(unittest.TestCase):
    def test_private_url_is_rejected(self):
        with self.assertRaisesRegex(ValueError, "本机或内网"):
            validate_public_http_url("http://127.0.0.1/private")

    def test_html_extraction_removes_scripts(self):
        content = b"<html><body><h1>Title</h1><script>bad()</script><p>Useful text</p></body></html>"
        self.assertEqual(extract_web_text(content, "text/html"), "Title Useful text")

    def test_missing_user_knowledge_base_is_reported(self):
        self.assertFalse(knowledge_base_assets_exist("definitely-missing-user"))


class GeneralQaServiceTests(unittest.IsolatedAsyncioTestCase):
    async def test_knowledge_base_answer_uses_local_retrieval_prompt(self):
        llm = FakeLlm()
        service = GeneralQaService(lambda: llm, lambda: FakeChatbot())

        answer = await service.answer_with_kb("问题", "6000971")

        self.assertEqual(answer, "测试答案")
        self.assertEqual(llm.prompt, "KB[6000971]:问题")

    async def test_url_answer_is_grounded_in_fetched_text(self):
        llm = FakeLlm()

        async def fetcher(_url):
            return "页面事实"

        service = GeneralQaService(lambda: llm, lambda: FakeChatbot(), fetcher)
        answer = await service.answer_url("https://example.com", "问题")

        self.assertEqual(answer, "测试答案")
        self.assertIn("页面事实", llm.prompt)
        self.assertIn("问题", llm.prompt)


if __name__ == "__main__":
    unittest.main()
