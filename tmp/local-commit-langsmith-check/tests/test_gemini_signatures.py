"""Exercise real SDK/LangGraph tool loops using an offline HTTP transport."""
import json
import sys
import unittest
from pathlib import Path

import httpx
from langchain_core.messages import messages_from_dict, messages_to_dict
from langchain_core.tools import tool
from langgraph.prebuilt import create_react_agent

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "agents"))
from src.utils.chat_model import ChatOpenAI


def completion(calls=None):
    return {"id": "test", "object": "chat.completion", "created": 1, "model": "gemini-test",
            "choices": [{"index": 0, "finish_reason": "tool_calls" if calls else "stop",
                         "message": {"role": "assistant", "content": None if calls else "verified result",
                                     **({"tool_calls": calls} if calls else {})}}]}


def call(identifier, signature=None):
    result = {"id": identifier, "type": "function", "function": {"name": "lookup", "arguments": '{"code":"600900"}'}}
    if signature:
        result["extra_content"] = {"google": {"thought_signature": signature}}
    return result


class TestGeminiSignatures(unittest.IsolatedAsyncioTestCase):
    async def test_parallel_and_sequential_tool_rounds_keep_each_original_signature(self):
        requests = []
        executed = []

        @tool
        def lookup(code: str) -> str:
            """Look up a test stock."""
            executed.append(code)
            return "local test data"

        def respond(request):
            payload = json.loads(request.content)
            requests.append(payload)
            if len(requests) == 1:
                return httpx.Response(200, json=completion([call("a", "opaque-A"), call("b")]))
            assistants = [m for m in payload["messages"] if m["role"] == "assistant"]
            self.assertEqual(assistants[0]["tool_calls"][0].get("extra_content"), {"google": {"thought_signature": "opaque-A"}})
            self.assertNotIn("extra_content", assistants[0]["tool_calls"][1])
            if len(requests) == 2:
                return httpx.Response(200, json=completion([call("c", "opaque-C")]))
            self.assertEqual(assistants[1]["tool_calls"][0]["extra_content"]["google"]["thought_signature"], "opaque-C")
            return httpx.Response(200, json=completion())

        async with httpx.AsyncClient(transport=httpx.MockTransport(respond)) as client:
            model = ChatOpenAI(api_key="test-only", model="gemini-test", base_url="https://generativelanguage.googleapis.com/v1beta/openai/", http_async_client=client)
            graph = create_react_agent(model, [lookup])
            result = await graph.ainvoke({"messages": [("user", "test lookup")]})
            self.assertEqual(result["messages"][-1].content, "verified result")
            restored = messages_from_dict(messages_to_dict(result["messages"]))
            replay = model._get_request_payload(restored)
            first = [m for m in replay["messages"] if m["role"] == "assistant"][0]
            self.assertEqual(first["tool_calls"][0]["extra_content"]["google"]["thought_signature"], "opaque-A")
        self.assertEqual(executed, ["600900"] * 3)

    async def test_other_providers_keep_standard_tool_payload(self):
        model = ChatOpenAI(api_key="test-only", model="regular", base_url="https://example.com/v1")
        message = model._create_chat_result(completion([call("a", "opaque-A")])).generations[0].message
        payload = model._get_request_payload([message])
        self.assertNotIn("extra_content", payload["messages"][0]["tool_calls"][0])


if __name__ == "__main__":
    unittest.main()
