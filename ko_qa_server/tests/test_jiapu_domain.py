import json
import unittest

from vue_api.jiapu_qa.domain import FamilyAuxiliaryService, FamilySessionStateStore, NormalAnswerService


class FakeStreamingLlm:
    def __init__(self):
        self.messages = None

    async def qwen2_stream(self, messages):
        self.messages = messages
        for chunk in ("罗允", "吉"):
            yield chunk


class FamilyAuxiliaryServiceTests(unittest.TestCase):
    def test_split_statement_question_uses_structured_result(self):
        llm = lambda _prompt: json.dumps(
            {"statement": "罗泽南是湖南人。", "inquire": "罗泽南的儿子是谁？"},
            ensure_ascii=False,
        )
        service = FamilyAuxiliaryService(llm)

        result = service.split_statement_question("罗泽南是湖南人。他的儿子是谁？")

        self.assertEqual(result["chenShu"], "罗泽南是湖南人。")
        self.assertEqual(result["wenTi"], "罗泽南的儿子是谁？")

    def test_split_statement_question_has_deterministic_fallback(self):
        service = FamilyAuxiliaryService(lambda _prompt: "")

        result = service.split_statement_question("罗泽南是湖南人。他的儿子是谁？")

        self.assertEqual(result["chenShu"], "罗泽南是湖南人。")
        self.assertEqual(result["wenTi"], "罗泽南的儿子是谁？")

    def test_extract_triples_normalizes_structured_result(self):
        llm = lambda _prompt: "```json\n" + json.dumps(
            {
                "items": ["罗泽南的儿子是罗允吉"],
                "triples": [["罗泽南", "儿子", "罗允吉"]],
            },
            ensure_ascii=False,
        ) + "\n```"
        service = FamilyAuxiliaryService(llm)

        result = service.extract_triples("罗泽南的儿子是罗允吉。")

        self.assertEqual(result["tiaoMu"], ["罗泽南的儿子是罗允吉"])
        self.assertEqual(result["triple"], [["罗泽南", "儿子", "罗允吉"]])

    def test_extract_triples_has_deterministic_fallback(self):
        service = FamilyAuxiliaryService(lambda _prompt: "not-json")

        result = service.extract_triples("罗泽南的儿子是罗允吉。")

        self.assertEqual(result["triple"], [["罗泽南", "儿子", "罗允吉"]])

    def test_merge_answer_returns_only_existing_citations(self):
        llm = lambda _prompt: json.dumps(
            {
                "answer": "罗泽南的儿子包括罗允吉。",
                "useful_items": ["罗泽南的儿子是罗允吉", "不存在的条目"],
            },
            ensure_ascii=False,
        )
        service = FamilyAuxiliaryService(llm)

        answer, items = service.merge_answer("", "罗泽南的儿子是罗允吉", "", "罗泽南的儿子是谁？")

        self.assertEqual(answer, "罗泽南的儿子包括罗允吉。")
        self.assertEqual(items, ["罗泽南的儿子是罗允吉"])

    def test_merge_multi_answer_preserves_history_and_appends_answer(self):
        service = FamilyAuxiliaryService(lambda _prompt: "")
        history = [{"role": "user", "content": "罗泽南的儿子是谁？"}]

        messages, items = service.merge_multi_answer("", "罗泽南的儿子是罗允吉", "", history)

        self.assertEqual(history, [{"role": "user", "content": "罗泽南的儿子是谁？"}])
        self.assertEqual(messages[-1]["role"], "assistant")
        self.assertIn("罗允吉", messages[-1]["content"])
        self.assertEqual(items, ["罗泽南的儿子是罗允吉"])


class FamilySessionStateStoreTests(unittest.TestCase):
    def test_states_are_isolated_by_session(self):
        store = FamilySessionStateStore()
        store.start("session-a")
        store.start("session-b")
        store.complete("session-a")

        self.assertEqual(store.get("session-a")["status"], "completed")
        self.assertEqual(store.get("session-b")["status"], "processing")

    def test_unknown_session_is_idle(self):
        state = FamilySessionStateStore().get("missing")

        self.assertEqual(state["stage"], 1)
        self.assertEqual(state["status"], "idle")


class NormalAnswerServiceTests(unittest.IsolatedAsyncioTestCase):
    async def test_stream_uses_latest_user_question_and_sse_format(self):
        llm = FakeStreamingLlm()
        service = NormalAnswerService(lambda: llm)
        history = [
            {"role": "user", "content": "第一问"},
            {"role": "assistant", "content": "第一答"},
            {"role": "user", "content": "罗泽南的儿子是谁？"},
        ]

        chunks = [chunk async for chunk in service.stream(history)]

        self.assertEqual(llm.messages, [{"role": "user", "content": "罗泽南的儿子是谁？"}])
        self.assertEqual(chunks, ["data: 罗允\n\n", "data: 吉\n\n"])


if __name__ == "__main__":
    unittest.main()
