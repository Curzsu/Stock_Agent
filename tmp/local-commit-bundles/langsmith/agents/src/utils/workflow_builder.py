"""
LangGraph 工作流构建工厂（P1-2）。

背景：
main.py 和 server.py 曾各自重复构建相同的 fan-out/fan-in 工作流
（start_node -> 4 个并行 analyst -> summarizer -> END），改一处忘改
另一处导致注释漂移（main.py:13 写"三个 agent"实际四个）。本模块抽取
共享的 build_workflow() 工厂，两个入口共用，消除重复。

拓扑：
    start_node
        |--> fundamental_analyst --|
        |--> technical_analyst  ----|--> summarizer --> END
        |--> value_analyst      ----|
        |--> news_analyst       ----|

LangGraph 保证 summarizer 等待所有 4 个 analyst 完成后才执行（fan-in barrier）。
"""
from typing import Awaitable, Callable, Optional

from langgraph.graph import StateGraph, END

from src.utils.state_definition import AgentState
from src.utils.observability import invoke_agent


def build_workflow(
    fundamental_agent: Callable,
    technical_agent: Callable,
    value_agent: Callable,
    news_agent: Callable,
    summary_agent: Callable,
    progress_callback: Optional[Callable[[str, str], Awaitable[None]]] = None,
    result_callback: Optional[Callable[[str, dict], Awaitable[None]]] = None,
):
    """构建并编译金融分析工作流图。

    Args:
        fundamental_agent / technical_agent / value_agent / news_agent:
            4 个分析 agent 协程，签名 async def agent(state: AgentState) -> dict。
        summary_agent: 汇总 agent 协程，接收汇聚后的 state。
        progress_callback: 可选的异步进度回调，签名
            async def cb(agent_key: str, status: str) -> None。
            agent_key ∈ {"fundamental","technical","value","news","summary"}，
            status ∈ {"running","completed"}。
            传 None 时仅保留可选的 LangSmith 业务追踪。

    Returns:
        编译后的 LangGraph，可直接 await app.ainvoke(initial_state)。
    """
    workflow = StateGraph(AgentState)

    # 起始节点：并行扇出的清晰起点，不修改状态
    workflow.add_node("start_node", lambda state: state)

    # 5 个 agent 节点：共享业务追踪，并按需调用进度/结果回调。
    workflow.add_node("fundamental_analyst", _wrap(fundamental_agent, "fundamental", progress_callback, result_callback))
    workflow.add_node("technical_analyst", _wrap(technical_agent, "technical", progress_callback, result_callback))
    workflow.add_node("value_analyst", _wrap(value_agent, "value", progress_callback, result_callback))
    workflow.add_node("news_analyst", _wrap(news_agent, "news", progress_callback, result_callback))
    workflow.add_node("summarizer", _wrap(summary_agent, "summary", progress_callback, result_callback))

    # 入口点
    workflow.set_entry_point("start_node")

    # 并行扇出：start_node -> 4 个分析 agent
    workflow.add_edge("start_node", "fundamental_analyst")
    workflow.add_edge("start_node", "technical_analyst")
    workflow.add_edge("start_node", "value_analyst")
    workflow.add_edge("start_node", "news_analyst")

    # 汇聚：4 个分析 agent -> summarizer（LangGraph 自动等待全部完成）
    workflow.add_edge("fundamental_analyst", "summarizer")
    workflow.add_edge("technical_analyst", "summarizer")
    workflow.add_edge("value_analyst", "summarizer")
    workflow.add_edge("news_analyst", "summarizer")

    # 结束
    workflow.add_edge("summarizer", END)

    return workflow.compile()


def _wrap(agent, agent_key, progress_callback, result_callback):
    """统一 agent 追踪及可选的进度、结果回调。"""
    async def wrapped(state):
        if progress_callback is not None:
            await progress_callback(agent_key, "running")
        result = await invoke_agent(agent, state, agent_key)
        if result_callback is not None:
            await result_callback(agent_key, result)
        if progress_callback is not None:
            await progress_callback(agent_key, "completed")
        return result

    return wrapped
