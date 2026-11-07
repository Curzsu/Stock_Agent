import asyncio
import sys
import unittest
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'agents'))

class ReuseTests(unittest.IsolatedAsyncioTestCase):
    async def test_mcp_empty_and_captcha_results_are_not_evidence(self):
        from src.utils.research_scope import successful
        self.assertFalse(successful(('', None)))
        self.assertFalse(successful(([], None)))
        self.assertFalse(successful('抱歉，百度搜索触发了安全验证，无法获取搜索结果。'))
        self.assertTrue(successful((['ROE=12%', 'EPS=1'], {'isError':False})))

    async def test_singleflight_cache_and_parameter_boundaries(self):
        from src.utils.research_scope import research_scope, reuse_query
        count = 0
        async def fetch():
            nonlocal count
            count += 1
            await asyncio.sleep(.01)
            return 'real data'
        async with research_scope():
            self.assertEqual(await asyncio.gather(*(reuse_query('profit', {'quarter':3}, fetch) for _ in range(4))), ['real data']*4)
            await reuse_query('profit', {'quarter':3}, fetch)
            self.assertEqual(count, 1)
            await reuse_query('profit', {'quarter':4}, fetch)
            self.assertEqual(count, 2)
        async with research_scope():
            await reuse_query('profit', {'quarter':3}, fetch)
        self.assertEqual(count, 3)

    async def test_failed_results_are_not_cached(self):
        from src.utils.research_scope import research_scope, reuse_query
        count = 0
        async def fetch():
            nonlocal count
            count += 1
            return 'Error: unavailable'
        async with research_scope():
            await reuse_query('probe', {}, fetch)
            await reuse_query('probe', {}, fetch)
        self.assertEqual(count, 2)

    async def test_cancelled_waiter_does_not_cancel_other_waiters(self):
        from src.utils.research_scope import research_scope, reuse_query
        release = asyncio.Event()
        async def fetch():
            await release.wait()
            return 'data'
        async with research_scope():
            one = asyncio.create_task(reuse_query('probe', {}, fetch))
            two = asyncio.create_task(reuse_query('probe', {}, fetch))
            await asyncio.sleep(0)
            one.cancel()
            await asyncio.gather(one, return_exceptions=True)
            release.set()
            self.assertEqual(await two, 'data')
