import asyncio
import json
import unittest
from unittest.mock import AsyncMock, patch

import httpx

from app_context import ChatRequest, Message
from routes import chat_lookup_routes


class FakeEngine:
    ready = True

    def retrieve(self, _query, top_k=4):
        return [{
            "text": "3000 NC start condition missing Remedy: Check machine ready signal.",
            "meta": {"code": "3000", "page": 12, "title": "NC start condition missing"},
        }]


class LlmProviderMatrixTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        previous = chat_lookup_routes.last_llm_source
        token = chat_lookup_routes.request_llm_source.set("none")
        self.addCleanup(setattr, chat_lookup_routes, "last_llm_source", previous)
        self.addCleanup(chat_lookup_routes.request_llm_source.reset, token)

    async def test_legacy_provider_environment_cannot_enable_external_calls(self):
        with (
            patch.dict("os.environ", {"LLM_PROVIDER": "school", "SCHOOL_API_BASE_URL": "https://unused.example"}),
            patch.object(chat_lookup_routes, "call_ollama", new=AsyncMock(return_value="local answer")) as ollama,
        ):
            answer = await chat_lookup_routes.call_llm([{"role": "user", "content": "q"}], 0.1, 64)
        self.assertEqual("local answer", answer)
        self.assertEqual("ollama", chat_lookup_routes.request_llm_source.get())
        ollama.assert_awaited_once()
        self.assertFalse(hasattr(chat_lookup_routes, "call_school_api"))

    async def test_local_failure_does_not_try_another_provider(self):
        with patch.object(chat_lookup_routes, "call_ollama", new=AsyncMock(side_effect=httpx.ConnectError("offline"))) as ollama:
            with self.assertRaises(httpx.ConnectError):
                await chat_lookup_routes.call_llm([], 0.1, 64)
        ollama.assert_awaited_once()
        self.assertEqual("none", chat_lookup_routes.request_llm_source.get())

    async def test_concurrent_success_and_failure_keep_request_local_source(self):
        async def ollama(messages, _temperature, _max_tokens):
            await asyncio.sleep(0)
            if messages[-1]["content"] == "fail":
                raise httpx.ConnectError("offline")
            return "local answer"

        async def invoke(prompt):
            try:
                answer = await chat_lookup_routes.call_llm([{"role": "user", "content": prompt}], 0.1, 64)
            except httpx.ConnectError:
                answer = "unavailable"
            return answer, chat_lookup_routes.request_llm_source.get()

        with patch.object(chat_lookup_routes, "call_ollama", side_effect=ollama):
            success, failed = await asyncio.gather(invoke("ok"), invoke("fail"))
        self.assertEqual(("local answer", "ollama"), success)
        self.assertEqual(("unavailable", "none"), failed)

    async def test_grounding_guard_retries_false_not_found_answer(self):
        docs = [{
            "text": "3000 Emergency stop. NC Start disable.",
            "meta": {"code": "3000", "page": 58, "title": "Emergency stop"},
        }]
        calls = AsyncMock(side_effect=[
            "無法在手冊中找到警報代碼 3000，請確認代碼或建立索引後再試。",
            "Alarm 3000 已找到；請檢查急停狀態與 NC Start disable。",
        ])

        with patch.object(chat_lookup_routes, "call_llm", new=calls):
            answer = await chat_lookup_routes.call_llm_with_retrieval_guard(
                [{"role": "system", "content": "grounded"}, {"role": "user", "content": "q"}],
                docs,
                "Alarm 3000 為什麼無法啟動？",
                0.1,
                128,
            )

        self.assertIn("Alarm 3000 已找到", answer)
        self.assertEqual(2, calls.await_count)
        self.assertIn("Retrieval metadata confirms", calls.await_args_list[1].args[0][0]["content"])

    async def test_grounding_guard_blocks_repeated_retrieval_contradiction(self):
        docs = [{
            "text": "3000 Emergency stop.",
            "meta": {"code": "3000", "page": 58, "title": "Emergency stop"},
        }]
        false_answer = "無法在手冊中找到警報代碼 3000，請確認代碼或建立索引後再試。"

        with patch.object(chat_lookup_routes, "call_llm", new=AsyncMock(return_value=false_answer)):
            answer = await chat_lookup_routes.call_llm_with_retrieval_guard(
                [{"role": "system", "content": "grounded"}],
                docs,
                "Alarm 3000 無法啟動",
                0.1,
                128,
            )

        self.assertIn("已在檢索資料中找到 Alarm 3000", answer)
        self.assertNotIn("無法在手冊中找到", answer)

    async def test_streaming_error_response_contains_readable_fallback_and_done(self):
        request = ChatRequest(messages=[Message(role="user", content="Alarm 3000")], stream=True)

        async def failed_stream(*_args, **_kwargs):
            raise RuntimeError("LLM timeout")
            yield ""  # pragma: no cover - keeps this function an async generator

        with (
            patch.object(chat_lookup_routes, "get_existing_engine", return_value=FakeEngine()),
            patch.object(chat_lookup_routes, "stream_ollama", new=failed_stream),
            patch.object(chat_lookup_routes, "save_rag_answer"),
            patch.object(chat_lookup_routes, "record_chat_error"),
            patch.object(chat_lookup_routes, "log_query"),
        ):
            response = await chat_lookup_routes.handle_chat(request, "808d")

        chunks = []
        async for chunk in response.body_iterator:
            chunks.append(chunk.decode("utf-8") if isinstance(chunk, bytes) else chunk)
        body = "".join(chunks)

        self.assertIn("目前無法連線至 LLM 服務", body)
        self.assertIn("來源：Alarm 3000 / P.12", body)
        self.assertIn("data: [DONE]", body)
        events = [
            json.loads(line[5:].strip())
            for line in body.splitlines()
            if line.startswith("data:") and line[5:].strip() != "[DONE]"
        ]
        self.assertEqual(1, len({event["id"] for event in events}))
        self.assertEqual(events[0]["id"], events[0]["rag"]["answer_id"])
        self.assertEqual("3000", events[0]["rag"]["citations"][0]["code"])
        self.assertEqual("no-cache", response.headers["cache-control"])
        self.assertEqual("no", response.headers["x-accel-buffering"])


if __name__ == "__main__":
    unittest.main()
