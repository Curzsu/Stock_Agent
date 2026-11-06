"""Offline regressions for nested deadlines and MCP session recovery."""
import asyncio
import os
import sys
import unittest
from pathlib import Path
from unittest.mock import AsyncMock, patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'agents'))
os.environ['LANGSMITH_TRACING'] = 'false'
os.environ['USE_TORCH'] = '0'
os.environ['USE_TF'] = '0'
os.environ['USE_FLAX'] = '0'
from langchain_core.tools import StructuredTool
from src.tools import mcp_client


class TestDeadlines(unittest.IsolatedAsyncioTestCase):
    async def test_react_can_finish_after_a_tool_timeout(self):
        from langchain_core.language_models.fake_chat_models import FakeMessagesListChatModel
        from langchain_core.messages import AIMessage, ToolMessage
        from langgraph.prebuilt import create_react_agent
        from src.utils.react_execution import run_react
        class Model(FakeMessagesListChatModel):
            def bind_tools(self, tools, **kwargs):
                return self
        async def hang():
            await asyncio.Event().wait()
        tool = StructuredTool.from_function(coroutine=hang, name='slow', description='Slow probe')
        model = Model(responses=[AIMessage(content='', tool_calls=[{'name': 'slow', 'args': {}, 'id': 'call1'}]),
                                 AIMessage(content='数据缺失，依据已有材料分析并保留判断边界。')])
        graph = create_react_agent(model, mcp_client.serialize_mcp_tools([tool], timeout_seconds=.01))
        result = await run_react(graph, {'messages': [('user', 'analyse')]}, timeout_seconds=2, recursion_limit=8)
        errors = [m for m in result['messages'] if isinstance(m, ToolMessage)]
        self.assertEqual(errors[0].status, 'error')
        self.assertIn('超时', errors[0].content)
        self.assertIn('数据缺失', result['messages'][-1].content)

    async def test_old_timeout_cleanup_cannot_close_replacement_session(self):
        old, new = object(), object()
        lock = asyncio.Lock()
        await lock.acquire()
        with patch.object(mcp_client, '_mcp_session_task', old), \
             patch.object(mcp_client, '_mcp_session_close_event', asyncio.Event()), \
             patch.object(mcp_client, '_get_init_lock', return_value=lock), \
             patch.object(mcp_client, '_close_cached_session', new_callable=AsyncMock) as close:
            cleanup = asyncio.create_task(mcp_client._retire_timed_out_owner(old))
            await asyncio.sleep(0)
            await asyncio.sleep(0)
            mcp_client._mcp_session_task = new
            lock.release()
            await cleanup
            close.assert_not_awaited()

    async def test_inner_timeout_is_not_reported_as_total_deadline(self):
        from src.utils.react_execution import run_react, AgentDeadlineExceeded
        class Agent:
            async def ainvoke(self, data, config=None):
                raise asyncio.TimeoutError('upstream')
        with self.assertRaisesRegex(RuntimeError, '内部') as caught:
            await run_react(Agent(), {}, timeout_seconds=1, recursion_limit=3)
        self.assertNotIsInstance(caught.exception, AgentDeadlineExceeded)

    async def test_total_deadline_cancels_child(self):
        from src.utils.react_execution import run_react, AgentDeadlineExceeded
        stopped = asyncio.Event()
        class Agent:
            async def ainvoke(self, data, config=None):
                try:
                    await asyncio.Event().wait()
                finally:
                    stopped.set()
        with self.assertRaises(AgentDeadlineExceeded):
            await run_react(Agent(), {}, timeout_seconds=.01, recursion_limit=3)
        self.assertTrue(stopped.is_set())

    async def test_failed_tool_is_recoverable_model_visible_error(self):
        async def hang():
            await asyncio.Event().wait()
        tool = StructuredTool.from_function(coroutine=hang, name='slow', description='Slow probe')
        protected = mcp_client.serialize_mcp_tools([tool], timeout_seconds=.01)
        result = await protected[0].ainvoke({})
        self.assertIn('slow', result)
        self.assertIn('超时', result)
        self.assertNotIn('480', result)

    async def test_composite_gets_independent_budget(self):
        async def query():
            await asyncio.sleep(.025)
            return 'data'
        tool = StructuredTool.from_function(coroutine=query, name='get_stock_analysis', description='Bundle')
        with patch.dict(os.environ, {'MCP_COMPOSITE_TOOL_TIMEOUT_SECONDS': '.1'}):
            result = await mcp_client.serialize_mcp_tools([tool], timeout_seconds=.01)[0].ainvoke({})
        self.assertEqual(result, 'data')

    async def test_timeout_retires_owner_before_next_queued_rpc(self):
        sessions = []
        class Context:
            closed = False
            async def __aenter__(self):
                sessions.append(self)
                return self
            async def __aexit__(self, *args):
                self.closed = True
        class Client:
            def session(self, name):
                return Context()
        async def load(session):
            async def query():
                if session is sessions[0]:
                    await asyncio.Event().wait()
                self.assertTrue(sessions[0].closed)
                return 'recovered'
            return [StructuredTool.from_function(coroutine=query, name='probe', description='Recovery')]
        with patch.object(mcp_client, 'MultiServerMCPClient', return_value=Client()), \
             patch.object(mcp_client, 'load_mcp_tools', side_effect=load), \
             patch.object(mcp_client, 'MCP_TOOL_TIMEOUT_SECONDS', .02):
            try:
                tools = await mcp_client.get_mcp_tools()
                first, second = await asyncio.gather(tools[0].ainvoke({}), tools[0].ainvoke({}))
                self.assertIn('超时', first)
                self.assertEqual(second, 'recovered')
                self.assertEqual(len(sessions), 2)
            finally:
                await mcp_client.close_mcp_client_sessions()


if __name__ == '__main__':
    unittest.main()
