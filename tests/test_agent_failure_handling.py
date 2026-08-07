"""
P1-4 回归测试：分析 Agent 失败不应静默吞掉。

背景：
4 个分析 agent 在 timeout/异常时既写 *_analysis_error 又把错误字符串
写进 *_analysis（本应只放正常结果）。summary 用 .get(*_analysis, "Not
available") 读取，错误文本被当成"分析结果"喂给 LLM，最终报告里混入
"基本面分析超时…请稍后重试"这类内容，且无降级标记。失败被静默吞掉。

期望行为（修复后）：
- 失败时只写 *_analysis_error，不写 *_analysis（让 summary 走 "Not available"）
- recursion_limit 应可配置（P1-1），不再硬编码 25
"""
import sys
import os
import asyncio
import unittest
from unittest.mock import patch, AsyncMock, MagicMock

PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, PROJECT_ROOT)
sys.path.insert(0, os.path.join(PROJECT_ROOT, "agents"))


def _make_state(query="分析茅台", stock_code="sh.600519", company_name="贵州茅台"):
    """构造一个合法的 AgentState，供 agent 函数使用。"""
    from src.utils.state_definition import AgentState
    return AgentState(
        messages=[],
        data={
            "query": query,
            "stock_code": stock_code,
            "company_name": company_name,
            "current_date": "2026-08-07",
            "current_date_cn": "2026年08月07日",
            "current_time": "12:00:00",
            "current_weekday_cn": "星期四",
            "current_time_info": "2026年08月07日 12:00:00",
        },
        metadata={},
    )


def _set_env():
    os.environ["OPENAI_COMPATIBLE_API_KEY"] = "test-key"
    os.environ["OPENAI_COMPATIBLE_BASE_URL"] = "http://localhost:9999"
    os.environ["OPENAI_COMPATIBLE_MODEL"] = "test-model"


class TestAgentFailureHandling(unittest.TestCase):
    """验证分析 agent 失败时不把错误塞进 *_analysis。"""

    def setUp(self):
        _set_env()

    def _patch_mcp_and_react(self, agent_module, react_behavior):
        """
        patch 掉 get_mcp_tools 和 create_react_agent。
        react_behavior: 'raise' / 'timeout' / 'success'
        """
        patches = []

        # get_mcp_tools 返回假工具列表
        async def fake_get_mcp_tools():
            return [MagicMock(name="fake_tool")]

        p1 = patch.object(agent_module, "get_mcp_tools", fake_get_mcp_tools)
        patches.append(p1)

        # create_react_agent 返回一个假 agent，其 ainvoke 按 behavior 行为
        fake_agent = MagicMock()

        async def fake_ainvoke(input_data, config=None):
            if react_behavior == "raise":
                raise RuntimeError("LLM boom")
            if react_behavior == "timeout":
                await asyncio.sleep(100)
            # success
            from langchain_core.messages import AIMessage
            return {"messages": [AIMessage(content="正常分析结果")]}

        fake_agent.ainvoke = fake_ainvoke
        p2 = patch.object(agent_module, "create_react_agent", return_value=fake_agent)
        patches.append(p2)

        for p in patches:
            p.start()
        return patches

    def _cleanup(self, patches):
        for p in patches:
            p.stop()

    def test_fundamental_timeout_does_not_write_analysis(self):
        """fundamental 超时：应只写 error key，不写 analysis key。"""
        from src.agents import fundamental_agent as mod
        patches = self._patch_mcp_and_react(mod, "timeout")
        try:
            state = _make_state()
            # 用很短的 wait_for 超时触发 timeout 路径
            # 注意：agent 内部有 asyncio.wait_for(timeout=480)，我们让它跑但
            # 直接调 agent 会等 480s。改为 patch wait_for 让它快速超时。
            import src.agents.fundamental_agent as fa

            async def fast_timeout(coro, timeout=None):
                raise asyncio.TimeoutError()

            with patch.object(fa.asyncio, "wait_for", fast_timeout):
                result = asyncio.run(mod.fundamental_agent(state))

            data = result.get("data", {})
            self.assertIn("fundamental_analysis_error", data,
                          "超时应写 fundamental_analysis_error")
            self.assertNotIn("fundamental_analysis", data,
                             "超时不应写 fundamental_analysis（否则错误文本被当分析结果喂给summary）")
        finally:
            self._cleanup(patches)

    def test_fundamental_exception_does_not_write_analysis(self):
        """fundamental 内层异常：应只写 error key，不写 analysis key。"""
        from src.agents import fundamental_agent as mod
        patches = self._patch_mcp_and_react(mod, "raise")
        try:
            state = _make_state()
            result = asyncio.run(mod.fundamental_agent(state))
            data = result.get("data", {})
            self.assertIn("fundamental_analysis_error", data)
            self.assertNotIn("fundamental_analysis", data,
                             "异常不应写 fundamental_analysis（否则错误文本被当分析结果）")
        finally:
            self._cleanup(patches)

    def test_technical_exception_does_not_write_analysis(self):
        """technical 异常：应只写 error key，不写 analysis key。"""
        from src.agents import technical_agent as mod
        patches = self._patch_mcp_and_react(mod, "raise")
        try:
            state = _make_state()
            result = asyncio.run(mod.technical_agent(state))
            data = result.get("data", {})
            self.assertIn("technical_analysis_error", data)
            self.assertNotIn("technical_analysis", data)
        finally:
            self._cleanup(patches)

    def test_value_exception_does_not_write_analysis(self):
        """value 异常：应只写 error key，不写 analysis key。"""
        from src.agents import value_agent as mod
        patches = self._patch_mcp_and_react(mod, "raise")
        try:
            state = _make_state()
            result = asyncio.run(mod.value_agent(state))
            data = result.get("data", {})
            self.assertIn("value_analysis_error", data)
            self.assertNotIn("value_analysis", data)
        finally:
            self._cleanup(patches)

    def test_news_exception_does_not_write_analysis(self):
        """news 异常：应只写 error key，不写 analysis key。"""
        from src.agents import news_agent as mod
        patches = self._patch_mcp_and_react(mod, "raise")
        try:
            state = _make_state()
            result = asyncio.run(mod.news_agent(state))
            data = result.get("data", {})
            self.assertIn("news_analysis_error", data)
            self.assertNotIn("news_analysis", data)
        finally:
            self._cleanup(patches)

    def test_success_still_writes_analysis(self):
        """成功路径：仍应写 analysis key（不破坏正常行为）。"""
        from src.agents import fundamental_agent as mod
        patches = self._patch_mcp_and_react(mod, "success")
        try:
            state = _make_state()
            result = asyncio.run(mod.fundamental_agent(state))
            data = result.get("data", {})
            self.assertIn("fundamental_analysis", data, "成功应写 analysis")
            self.assertNotIn("fundamental_analysis_error", data, "成功不应写 error")
        finally:
            self._cleanup(patches)


if __name__ == "__main__":
    unittest.main(verbosity=2)
