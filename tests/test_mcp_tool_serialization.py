import asyncio
import sys
import unittest
from pathlib import Path
from unittest.mock import patch

from langchain_core.tools import StructuredTool


WORKSPACE = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(WORKSPACE / "agents"))

from src.tools import mcp_client


class TestMcpToolSerialization(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        self._reset_mcp_state()

    def tearDown(self):
        self._reset_mcp_state()

    @staticmethod
    def _reset_mcp_state():
        for name in (
            "_mcp_tools",
            "_mcp_client_instance",
            "_mcp_session_context",
            "_mcp_session",
            "_mcp_session_loop",
            "_mcp_session_task",
            "_mcp_session_close_event",
            "_mcp_init_lock",
            "_mcp_init_lock_loop",
            "_mcp_tool_lock",
            "_mcp_tool_lock_loop",
        ):
            if hasattr(mcp_client, name):
                setattr(mcp_client, name, None)

    async def test_get_mcp_tools_reuses_one_explicit_session(self):
        class FakeSessionContext:
            def __init__(self):
                self.enter_count = 0
                self.exit_count = 0
                self.session = object()

            async def __aenter__(self):
                self.enter_count += 1
                return self.session

            async def __aexit__(self, exc_type, exc, traceback):
                self.exit_count += 1

        class FakeClient:
            def __init__(self, context):
                self.context = context
                self.session_names = []

            def session(self, name):
                self.session_names.append(name)
                return self.context

        async def probe() -> str:
            return "ok"

        context = FakeSessionContext()
        client = FakeClient(context)
        loaded_tools = [
            StructuredTool.from_function(
                name="persistent_probe",
                description="Probe persistent MCP session reuse.",
                coroutine=probe,
            )
        ]
        load_count = 0

        async def fake_load_mcp_tools(session):
            nonlocal load_count
            load_count += 1
            self.assertIs(session, context.session)
            return loaded_tools

        with (
            patch.object(mcp_client, "MultiServerMCPClient", return_value=client),
            patch.object(
                mcp_client,
                "load_mcp_tools",
                side_effect=fake_load_mcp_tools,
                create=True,
            ),
        ):
            first = await mcp_client.get_mcp_tools()
            second = await mcp_client.get_mcp_tools()

        self.assertIs(first, second)
        self.assertEqual(client.session_names, ["a_share_mcp_v2"])
        self.assertEqual(context.enter_count, 1)
        self.assertEqual(context.exit_count, 0)
        self.assertEqual(load_count, 1)
        await mcp_client.close_mcp_client_sessions()
        self.assertEqual(context.exit_count, 1)

    async def test_close_persistent_session_is_idempotent(self):
        class FakeSessionContext:
            def __init__(self):
                self.exit_calls = []

            async def __aenter__(self):
                return object()

            async def __aexit__(self, exc_type, exc, traceback):
                self.exit_calls.append((exc_type, exc, traceback))

        class FakeClient:
            def __init__(self, context):
                self.context = context

            def session(self, name):
                self.name = name
                return self.context

        async def probe() -> str:
            return "ok"

        context = FakeSessionContext()
        client = FakeClient(context)
        loaded_tools = [
            StructuredTool.from_function(
                name="close_probe",
                description="Probe persistent MCP session close.",
                coroutine=probe,
            )
        ]

        with (
            patch.object(mcp_client, "MultiServerMCPClient", return_value=client),
            patch.object(
                mcp_client,
                "load_mcp_tools",
                return_value=loaded_tools,
            ),
        ):
            await mcp_client.get_mcp_tools()
            await mcp_client.close_mcp_client_sessions()
            await mcp_client.close_mcp_client_sessions()

        self.assertEqual(context.exit_calls, [(None, None, None)])
        for name in (
            "_mcp_tools",
            "_mcp_client_instance",
            "_mcp_session_context",
            "_mcp_session",
            "_mcp_session_loop",
        ):
            self.assertIsNone(getattr(mcp_client, name))

    async def test_session_entry_and_exit_run_in_same_task(self):
        class TaskBoundSessionContext:
            def __init__(self):
                self.enter_task = None
                self.exit_task = None

            async def __aenter__(self):
                self.enter_task = asyncio.current_task()
                return object()

            async def __aexit__(self, exc_type, exc, traceback):
                self.exit_task = asyncio.current_task()

        class FakeClient:
            def __init__(self, context):
                self.context = context

            def session(self, name):
                return self.context

        async def probe() -> str:
            return "ok"

        context = TaskBoundSessionContext()
        loaded_tools = [
            StructuredTool.from_function(
                name="task_identity_probe",
                description="Probe MCP session task ownership.",
                coroutine=probe,
            )
        ]
        with (
            patch.object(
                mcp_client,
                "MultiServerMCPClient",
                return_value=FakeClient(context),
            ),
            patch.object(
                mcp_client,
                "load_mcp_tools",
                return_value=loaded_tools,
            ),
        ):
            await mcp_client.get_mcp_tools()
            await mcp_client.close_mcp_client_sessions()

        self.assertIs(context.enter_task, context.exit_task)

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
