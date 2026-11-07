"""
P1-2 回归测试：build_workflow 工厂固化工作流拓扑。

背景：
main.py 和 server.py 各自重复构建相同的 LangGraph 工作流（start_node ->
4 个并行 analyst -> summarizer -> END），改一处忘改另一处（main.py:13
注释已漂移成"三个 agent"）。抽取共享 build_workflow() 工厂消除重复。

本测试固化工作流的核心行为契约：
1. 4 个分析 agent 从 start_node 并行执行
2. summarizer 在所有 4 个 analyst 完成后才执行（fan-in barrier）
3. progress_callback 在每个 agent 开始/完成时被调用
4. 无 progress_callback 时（CLI 路径）图仍能正常执行
"""
import sys
import os
import asyncio
import unittest
from unittest.mock import AsyncMock, MagicMock

PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, PROJECT_ROOT)
sys.path.insert(0, os.path.join(PROJECT_ROOT, "agents"))

from src.utils.state_definition import AgentState


def _make_fake_agent(result_key, marker):
    """造一个假 agent：往 state.data 写入 result_key=marker，返回新 state。"""
    async def fake(state):
        data = dict(state.get("data", {}))
        data[result_key] = marker
        return {"data": data, "messages": state.get("messages", []), "metadata": state.get("metadata", {})}
    return fake


def _make_initial_state():
    return AgentState(messages=[], data={"query": "test", "stock_code": "sh.600519"}, metadata={})


class TestBuildWorkflow(unittest.TestCase):
    """验证 build_workflow 工厂的拓扑行为。"""

    def test_four_analysts_run_in_parallel_then_summary(self):
        """4 个 analyst 并行执行，summarizer 最后，结果汇聚正确。"""
        from src.utils.workflow_builder import build_workflow

        fundamental = _make_fake_agent("fundamental_analysis", "FUND")
        technical = _make_fake_agent("technical_analysis", "TECH")
        value = _make_fake_agent("value_analysis", "VAL")
        news = _make_fake_agent("news_analysis", "NEWS")

        summary_calls = []
        async def summary(state):
            data = dict(state.get("data", {}))
            # 验证 fan-in：summary 执行时 4 个分析结果都已就位
            summary_calls.append(dict(data))
            data["final_report"] = "FINAL"
            return {"data": data, "messages": [], "metadata": {}}

        app = build_workflow(
            fundamental_agent=fundamental,
            technical_agent=technical,
            value_agent=value,
            news_agent=news,
            summary_agent=summary,
        )

        final_state = asyncio.run(app.ainvoke(_make_initial_state()))

        # 4 个分析结果都应存在
        data = final_state["data"]
        self.assertEqual(data.get("fundamental_analysis"), "FUND")
        self.assertEqual(data.get("technical_analysis"), "TECH")
        self.assertEqual(data.get("value_analysis"), "VAL")
        self.assertEqual(data.get("news_analysis"), "NEWS")
        # summary 执行了，且执行时 4 个结果都在（fan-in barrier 生效）
        self.assertEqual(len(summary_calls), 1)
        self.assertEqual(summary_calls[0].get("fundamental_analysis"), "FUND")
        self.assertEqual(summary_calls[0].get("technical_analysis"), "TECH")
        self.assertEqual(summary_calls[0].get("value_analysis"), "VAL")
        self.assertEqual(summary_calls[0].get("news_analysis"), "NEWS")
        # final_report 来自 summary
        self.assertEqual(data.get("final_report"), "FINAL")

    def test_progress_callback_invoked(self):
        """progress_callback 在每个 agent 开始/完成时被调用。"""
        from src.utils.workflow_builder import build_workflow

        progress_log = []

        async def progress_cb(agent_key, status):
            progress_log.append((agent_key, status))

        app = build_workflow(
            fundamental_agent=_make_fake_agent("fundamental_analysis", "F"),
            technical_agent=_make_fake_agent("technical_analysis", "T"),
            value_agent=_make_fake_agent("value_analysis", "V"),
            news_agent=_make_fake_agent("news_analysis", "N"),
            summary_agent=_make_fake_agent("final_report", "R"),
            progress_callback=progress_cb,
        )

        asyncio.run(app.ainvoke(_make_initial_state()))

        # 每个 agent 应有 running + completed 两个回调
        keys = {"fundamental", "technical", "value", "news", "summary"}
        completed_keys = {k for k, s in progress_log if s == "completed"}
        self.assertEqual(completed_keys, keys,
                         f"所有 agent 都应触发 completed，实际: {completed_keys}")

    def test_result_callback_receives_each_agent_result(self):
        from src.utils.workflow_builder import build_workflow

        results = {}

        async def result_cb(agent_key, result):
            results[agent_key] = result["data"]

        app = build_workflow(
            fundamental_agent=_make_fake_agent("fundamental_analysis", "F"),
            technical_agent=_make_fake_agent("technical_analysis", "T"),
            value_agent=_make_fake_agent("value_analysis", "V"),
            news_agent=_make_fake_agent("news_analysis", "N"),
            summary_agent=_make_fake_agent("final_report", "R"),
            result_callback=result_cb,
        )

        asyncio.run(app.ainvoke(_make_initial_state()))

        self.assertEqual(results["fundamental"]["fundamental_analysis"], "F")
        self.assertEqual(results["technical"]["technical_analysis"], "T")
        self.assertEqual(results["value"]["value_analysis"], "V")
        self.assertEqual(results["news"]["news_analysis"], "N")
        self.assertEqual(results["summary"]["final_report"], "R")

    def test_no_progress_callback_works(self):
        """不传 progress_callback（CLI 路径）时图仍正常执行。"""
        from src.utils.workflow_builder import build_workflow

        app = build_workflow(
            fundamental_agent=_make_fake_agent("fundamental_analysis", "F"),
            technical_agent=_make_fake_agent("technical_analysis", "T"),
            value_agent=_make_fake_agent("value_analysis", "V"),
            news_agent=_make_fake_agent("news_analysis", "N"),
            summary_agent=_make_fake_agent("final_report", "R"),
        )

        final_state = asyncio.run(app.ainvoke(_make_initial_state()))
        self.assertEqual(final_state["data"]["final_report"], "R")
        self.assertEqual(final_state["data"]["fundamental_analysis"], "F")


if __name__ == "__main__":
    unittest.main(verbosity=2)
