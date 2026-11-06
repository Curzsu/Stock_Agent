import asyncio
import sys
import unittest
from pathlib import Path
from unittest.mock import patch
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'agents'))
from langchain_core.messages import AIMessage, ToolMessage

class RecoveryTests(unittest.IsolatedAsyncioTestCase):
    async def test_captcha_is_not_used_to_synthesize_a_report(self):
        from src.utils.react_execution import run_react
        class Agent:
            async def ainvoke(self, data, config=None):
                return {'messages': [ToolMessage(content='抱歉，百度搜索触发了安全验证，无法获取搜索结果。',tool_call_id='1'),
                        AIMessage(content='unfinished',response_metadata={'finish_reason':'length'})]}
        class Llm:
            async def ainvoke(self, messages):
                raise AssertionError('No real evidence: do not synthesize')
        with self.assertRaisesRegex(ValueError,'有效资料'):
            await run_react(Agent(), {}, timeout_seconds=2,recursion_limit=3,llm=Llm())

    async def test_collection_reserves_time_for_one_evidence_based_synthesis(self):
        from src.utils.react_execution import run_react
        stopped = asyncio.Event()
        class Agent:
            async def ainvoke(self, data, config=None):
                await config['callbacks'][0].on_tool_end(ToolMessage(content='ROE=12%',tool_call_id='1'))
                try:
                    await asyncio.Event().wait()
                finally:
                    stopped.set()
        class Llm:
            async def ainvoke(self, messages):
                return AIMessage(content='根据ROE为12%的资料完成分析，并注明缺失项。')
        result = await run_react(Agent(), {}, timeout_seconds=.15,recursion_limit=3,llm=Llm())
        self.assertTrue(stopped.is_set())
        self.assertIn('缺失',result['messages'][-1].content)

    async def test_length_rewrites_once_with_evidence_without_requery(self):
        from src.utils.react_execution import run_react
        class Agent:
            async def ainvoke(self, data, config=None):
                return {'messages': [ToolMessage(content='ROE=12%', tool_call_id='1'),
                        AIMessage(content='unfinished', response_metadata={'finish_reason':'length'})]}
        class Llm:
            calls = 0
            async def ainvoke(self, messages):
                self.calls += 1
                assert 'ROE=12%' in str(messages)
                return AIMessage(content='依据ROE为12%的数据给出完整分析。')
        llm = Llm()
        result = await run_react(Agent(), {'messages': []}, timeout_seconds=2, recursion_limit=3, llm=llm)
        self.assertEqual(llm.calls, 1)
        self.assertIn('完整分析', result['messages'][-1].content)

    async def test_role_tools_exclude_news_and_composite(self):
        from src.utils.research_scope import tools_for_role
        from types import SimpleNamespace
        tools = [SimpleNamespace(name=n) for n in ['crawl_news','get_stock_analysis','get_profit_data','get_historical_k_data']]
        self.assertEqual([t.name for t in tools_for_role(tools,'technical')], ['get_historical_k_data'])

class QuotaTests(unittest.TestCase):
    def test_exhausted_quota_prevents_login(self):
        import importlib, tempfile, os
        from unittest.mock import Mock
        from src.utils.baostock_helper import safe_query
        runtime = importlib.import_module(safe_query.__module__)
        with tempfile.TemporaryDirectory() as folder, patch.dict(os.environ, {'FINEX_BAOSTOCK_STATE_DIR':folder,'BAOSTOCK_DAILY_REQUEST_LIMIT':'1'}):
            runtime._count_request()
            with patch.object(runtime.bs,'login',Mock()) as login:
                with self.assertRaisesRegex(runtime.BaostockDataError,'配额'):
                    runtime.safe_query(Mock())
                login.assert_not_called()

    def test_actual_sends_stop_at_quota(self):
        import importlib, tempfile, os, time
        from unittest.mock import Mock
        from src.utils.baostock_helper import safe_query
        runtime = importlib.import_module(safe_query.__module__)
        transport = Mock(return_value='ok')
        with tempfile.TemporaryDirectory() as folder, patch.dict(os.environ, {'FINEX_BAOSTOCK_STATE_DIR':folder,'BAOSTOCK_DAILY_REQUEST_LIMIT':'2'}), \
             patch.object(runtime.bs_transport, 'send_msg', transport), \
             patch.object(runtime.bs_context, 'default_socket', None, create=True), patch.object(runtime, '_end_session'):
            with runtime._query_guard(time.monotonic()+10):
                runtime.bs_transport.send_msg('login')
                runtime.bs_transport.send_msg('page')
                with self.assertRaises(runtime.BaostockDataError):
                    runtime.bs_transport.send_msg('page2')
        self.assertEqual(transport.call_count, 2)

    def test_quota_survives_reload_and_stops_before_send(self):
        import importlib, tempfile, os
        from src.utils.baostock_helper import safe_query
        runtime = importlib.import_module(safe_query.__module__)
        with tempfile.TemporaryDirectory() as folder, patch.dict(os.environ, {'FINEX_BAOSTOCK_STATE_DIR':folder,'BAOSTOCK_DAILY_REQUEST_LIMIT':'2'}):
            runtime._count_request()
            runtime._count_request()
            with self.assertRaisesRegex(runtime.BaostockDataError, '配额'):
                runtime._count_request()
            import json
            self.assertEqual(json.loads((Path(folder)/'request-count.json').read_text())['count'],2)
