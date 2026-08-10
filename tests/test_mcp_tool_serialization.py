import asyncio
import sys
import unittest
from pathlib import Path

from langchain_core.tools import StructuredTool


WORKSPACE = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(WORKSPACE / "agents"))

from src.tools import mcp_client


class TestMcpToolSerialization(unittest.IsolatedAsyncioTestCase):
    async def test_concurrent_tool_calls_are_serialized(self):
        if not hasattr(mcp_client, "serialize_mcp_tools"):
            self.fail("serialize_mcp_tools is required to protect Baostock sessions")

        active = 0
        maximum_active = 0

        async def run_probe(value: int) -> int:
            nonlocal active, maximum_active
            active += 1
            maximum_active = max(maximum_active, active)
            await asyncio.sleep(0.03)
            active -= 1
            return value

        tools = [
            StructuredTool.from_function(
                name=f"probe_{value}",
                description="Probe tool concurrency.",
                coroutine=lambda value=value: run_probe(value),
            )
            for value in (1, 2)
        ]

        protected = mcp_client.serialize_mcp_tools(tools, timeout_seconds=1)
        results = await asyncio.gather(*(tool.ainvoke({}) for tool in protected))

        self.assertEqual(results, [1, 2])
        self.assertEqual(maximum_active, 1)

    async def test_hanging_tool_call_honors_its_deadline(self):
        async def hang() -> str:
            await asyncio.sleep(0.15)
            return "late"

        tool = StructuredTool.from_function(
            name="hanging_probe",
            description="Probe tool timeout.",
            coroutine=hang,
        )
        protected = mcp_client.serialize_mcp_tools([tool], timeout_seconds=0.02)

        with self.assertRaises(asyncio.TimeoutError):
            await protected[0].ainvoke({})


if __name__ == "__main__":
    unittest.main()
