"""
P2-7 端到端冒烟测试：验证「4 个分析 agent 并行 -> summary 汇总」主链路。

背景：
test_workflow_builder.py 已经用 mock agent 函数测了拓扑，但那 mock 的是
整个 agent 函数，不是「接近真实」的端到端。本测试 mock 更底层：
- mock get_mcp_tools：避免真实 MCP 子进程
- mock create_react_agent：返回假 agent，其 ainvoke 返回含 AIMessage 的标准响应
- mock ChatOpenAI（summary_agent 用）：避免真实 LLM 调用
- mock generate_pdf_background：避免真实文件/PDF 操作

让真正的 agent 函数（fundamental_agent 等）跑起来，验证它们能正确处理
state、调 mock 工具、写回结果，最终 summary 汇总出 final_report。

注意：本测试因 langchain/langgraph 的 PyO3 重复初始化问题，不能和别的测试
套件同进程跑（已知环境限制）。独立跑通过即可：
    venv/Scripts/python.exe -m unittest tests.test_end_to_end -v
"""
import sys
import os
import glob
import asyncio
import unittest
from unittest.mock import patch, MagicMock

# 让 `from src...` 能解析到 agents/src 下
PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, PROJECT_ROOT)
sys.path.insert(0, os.path.join(PROJECT_ROOT, "agents"))

from langchain_core.messages import AIMessage


# ----------------------------------------------------------------------------
# 环境与 state 构造
# ----------------------------------------------------------------------------
def _set_env():
    """注入测试用环境变量，并强制 summary 走 API 路径（不走 local FinR1）。"""
    os.environ["OPENAI_COMPATIBLE_API_KEY"] = "test-key"
    os.environ["OPENAI_COMPATIBLE_BASE_URL"] = "http://localhost:9999"
    os.environ["OPENAI_COMPATIBLE_MODEL"] = "test-model"
    # summary_agent.get_model_choice() 读这个，默认 "api"；显式设保险
    os.environ["USE_LOCAL_MODEL"] = "api"


def _make_initial_state():
    """构造一个合法的 AgentState，包含 4 个 agent 都需要的查询与时间信息。"""
    from src.utils.state_definition import AgentState
    return AgentState(
        messages=[],
        data={
            "query": "分析贵州茅台",
            "stock_code": "sh.600519",
            "company_name": "贵州茅台",
            "current_date": "2026-08-07",
            "current_date_cn": "2026年08月07日",
            "current_time": "12:00:00",
            "current_weekday_cn": "星期四",
            "current_time_info": "2026年08月07日 12:00:00",
        },
        metadata={},
    )


# ----------------------------------------------------------------------------
# mock 工厂
# ----------------------------------------------------------------------------
def _make_fake_react_agent(content="这是模拟分析结果", *, raise_exc=None):
    """
    造一个假 ReAct agent 对象：create_react_agent(llm, tools) 的返回值。
    - content: ainvoke 返回的 AIMessage 内容
    - raise_exc: 若非 None，ainvoke 抛出该异常（用于失败用例）
    """
    fake_agent = MagicMock(name="fake_react_agent")

    async def fake_ainvoke(input_data, config=None):
        if raise_exc is not None:
            raise raise_exc
        return {"messages": [AIMessage(content=content)]}

    fake_agent.ainvoke = fake_ainvoke
    return fake_agent


async def _fake_get_mcp_tools():
    """假 MCP 工具列表，避免真实 MCP 子进程。"""
    return [MagicMock(name="fake_tool")]


def _make_fake_llm(report_content="这是模拟综合报告内容", llm_calls=None):
    """
    造一个假 summary LLM：ChatOpenAI(...) 的返回值。
    summary_agent 调 await llm.ainvoke(messages) 并取 .content。
    llm_calls 非空时，每次 ainvoke 往里 append 一条记录（用于断言 summary 被调）。
    """
    fake_llm = MagicMock(name="fake_summary_llm")

    async def fake_ainvoke(messages):
        if llm_calls is not None:
            llm_calls.append(messages)
        return MagicMock(content=report_content)

    fake_llm.ainvoke = fake_ainvoke
    return fake_llm


async def _fake_generate_pdf_background(*args, **kwargs):
    """假后台 PDF 生成，no-op，避免真实文件/PDF 引擎操作。"""
    return None


# ----------------------------------------------------------------------------
# patch 装配
# ----------------------------------------------------------------------------
# 4 个分析 agent 模块路径前缀（每个模块各自 import 了 get_mcp_tools /
# create_react_agent，需 patch 各模块的引用）
_AGENT_MODULES = [
    "src.agents.fundamental_agent",
    "src.agents.technical_agent",
    "src.agents.value_agent",
    "src.agents.news_agent",
]


def _patch_analysis_agents(contents=None, failures=None):
    """
    patch 4 个分析 agent 模块的 get_mcp_tools 和 create_react_agent。

    Args:
        contents: dict[module_path -> AIMessage content]，未列出的用默认值。
        failures: dict[module_path -> Exception]，该模块的 ainvoke 抛此异常。

    Returns:
        list[已 start 的 patcher]，调用方 finally 逐个 stop。
    """
    contents = contents or {}
    failures = failures or {}
    patchers = []

    for mod_path in _AGENT_MODULES:
        module = sys.modules[mod_path]
        p1 = patch.object(module, "get_mcp_tools", _fake_get_mcp_tools)
        p1.start()
        patchers.append(p1)

        exc = failures.get(mod_path)
        if exc is not None:
            fake_agent = _make_fake_react_agent(raise_exc=exc)
        else:
            content = contents.get(mod_path, "这是模拟分析结果")
            fake_agent = _make_fake_react_agent(content=content)

        p2 = patch.object(module, "create_react_agent", return_value=fake_agent)
        p2.start()
        patchers.append(p2)

    return patchers


def _patch_summary(report_content="这是模拟综合报告内容"):
    """
    patch summary_agent 模块的 ChatOpenAI 与 generate_pdf_background。
    返回 (patchers, llm_calls) -- llm_calls 记录 summary 是否真的调了 LLM。

    summary_agent 里是 `llm = ChatOpenAI(...)` 调用形式，故用一个 callable
    工厂替换 ChatOpenAI：每次被「调用」就返回一个假 llm。
    """
    from src.agents import summary_agent as summary_mod

    llm_calls = []

    def fake_chat_openai_factory(*args, **kwargs):
        return _make_fake_llm(report_content=report_content, llm_calls=llm_calls)

    p1 = patch.object(summary_mod, "ChatOpenAI", new=fake_chat_openai_factory)
    p1.start()

    p2 = patch.object(summary_mod, "generate_pdf_background", _fake_generate_pdf_background)
    p2.start()

    return [p1, p2], llm_calls


# ----------------------------------------------------------------------------
# 测试用例
# ----------------------------------------------------------------------------
class TestEndToEnd(unittest.TestCase):
    """端到端冒烟：4 agent 并行 -> summary 汇总 主链路。"""

    def setUp(self):
        _set_env()
        # 记录测试前已存在的报告文件，tearDown 只清本测试新建的，避免误删
        self._reports_dir = os.path.join(
            PROJECT_ROOT, "agents", "reports", "md")
        self._pre_reports = set(glob.glob(os.path.join(self._reports_dir, "*.md")))

    def tearDown(self):
        # summary_agent 会把最终报告 .md 写到 agents/reports/md/，清理本测试产物
        if not os.path.isdir(self._reports_dir):
            return
        for path in glob.glob(os.path.join(self._reports_dir, "*.md")):
            if path not in self._pre_reports:
                try:
                    os.remove(path)
                except OSError:
                    pass

    def test_full_workflow_produces_report(self):
        """完整 workflow：4 agent 都成功，summary 汇总出 final_report。"""
        from src.utils.workflow_builder import build_workflow
        from src.agents.fundamental_agent import fundamental_agent
        from src.agents.technical_agent import technical_agent
        from src.agents.value_agent import value_agent
        from src.agents.news_agent import news_agent
        from src.agents.summary_agent import summary_agent

        analysis_patchers = _patch_analysis_agents(contents={
            "src.agents.fundamental_agent": "基本面模拟分析：财务稳健，ROE 15%。",
            "src.agents.technical_agent": "技术面模拟分析：MACD 金叉，RSI 55。",
            "src.agents.value_agent": "估值模拟分析：PE 15 倍，低于行业均值。",
            "src.agents.news_agent": "新闻模拟分析：近期利好，机构上调评级。",
        })
        summary_patchers, llm_calls = _patch_summary(
            report_content="# 贵州茅台(sh.600519) 综合分析报告\n\n## 执行摘要\n模拟综合报告。"
        )

        try:
            app = build_workflow(
                fundamental_agent=fundamental_agent,
                technical_agent=technical_agent,
                value_agent=value_agent,
                news_agent=news_agent,
                summary_agent=summary_agent,
            )

            final_state = asyncio.run(app.ainvoke(_make_initial_state()))
        finally:
            for p in summary_patchers:
                p.stop()
            for p in analysis_patchers:
                p.stop()

        data = final_state["data"]

        # 1) 4 个分析结果都在，且都是模拟内容（非错误文本）
        self.assertIn("fundamental_analysis", data)
        self.assertIn("technical_analysis", data)
        self.assertIn("value_analysis", data)
        self.assertIn("news_analysis", data)
        self.assertIn("基本面", data["fundamental_analysis"])
        self.assertIn("技术面", data["technical_analysis"])
        self.assertIn("估值", data["value_analysis"])
        self.assertIn("新闻", data["news_analysis"])
        # 不应有 error key
        for err_key in ("fundamental_analysis_error", "technical_analysis_error",
                        "value_analysis_error", "news_analysis_error", "summary_error"):
            self.assertNotIn(err_key, data, f"成功路径不应出现 {err_key}")

        # 2) final_report 存在且非空
        self.assertIn("final_report", data)
        self.assertTrue(data["final_report"], "final_report 不应为空")
        self.assertIn("综合分析报告", data["final_report"])

        # 3) summary 的 LLM 被真正调用过一次
        self.assertEqual(len(llm_calls), 1, "summary 应恰好调用一次 LLM ainvoke")

    def test_workflow_handles_agent_failure_gracefully(self):
        """
        一个分析 agent 抛异常时，workflow 仍完成：
        - 失败的那个只有 *_analysis_error，没有 *_analysis（P1-4 端到端验证）
        - 其他 3 个 agent 结果正常
        - summary 仍被调用并生成 final_report
        """
        from src.utils.workflow_builder import build_workflow
        from src.agents.fundamental_agent import fundamental_agent
        from src.agents.technical_agent import technical_agent
        from src.agents.value_agent import value_agent
        from src.agents.news_agent import news_agent
        from src.agents.summary_agent import summary_agent

        # 让 fundamental_agent 的 ainvoke 抛异常
        analysis_patchers = _patch_analysis_agents(
            contents={
                "src.agents.technical_agent": "技术面模拟分析：MACD 金叉。",
                "src.agents.value_agent": "估值模拟分析：PE 合理。",
                "src.agents.news_agent": "新闻模拟分析：利好。",
            },
            failures={
                "src.agents.fundamental_agent": RuntimeError("模拟 fundamental LLM 故障"),
            },
        )
        summary_patchers, llm_calls = _patch_summary(
            report_content="# 综合分析报告（含部分分析缺失）\n\n## 执行摘要\n降级报告。"
        )

        try:
            app = build_workflow(
                fundamental_agent=fundamental_agent,
                technical_agent=technical_agent,
                value_agent=value_agent,
                news_agent=news_agent,
                summary_agent=summary_agent,
            )

            final_state = asyncio.run(app.ainvoke(_make_initial_state()))
        finally:
            for p in summary_patchers:
                p.stop()
            for p in analysis_patchers:
                p.stop()

        data = final_state["data"]

        # 1) fundamental 失败：只有 error key，没有 analysis key（P1-4 契约）
        self.assertIn("fundamental_analysis_error", data,
                      "失败的 agent 应写 *_analysis_error")
        self.assertNotIn("fundamental_analysis", data,
                         "失败的 agent 不应写 *_analysis（否则错误文本被当分析结果喂给 summary）")

        # 2) 其他 3 个 agent 正常
        self.assertIn("technical_analysis", data)
        self.assertIn("value_analysis", data)
        self.assertIn("news_analysis", data)
        self.assertNotIn("technical_analysis_error", data)
        self.assertNotIn("value_analysis_error", data)
        self.assertNotIn("news_analysis_error", data)

        # 3) summary 仍被调用并生成 final_report（workflow 没因单 agent 失败而中断）
        self.assertEqual(len(llm_calls), 1, "即使一个 agent 失败，summary 仍应被调用一次")
        self.assertIn("final_report", data)
        self.assertTrue(data["final_report"], "summary 应生成降级 final_report")


if __name__ == "__main__":
    unittest.main(verbosity=2)
