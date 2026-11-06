"""Distinguish the overall analysis deadline from nested request timeouts."""
import asyncio
import os
import time
import math
from langgraph.errors import GraphRecursionError
from langchain_core.callbacks import AsyncCallbackHandler
from langchain_core.messages import HumanMessage, ToolMessage
from src.utils.agent_output import extract_analysis_text
from src.utils.research_scope import successful


class AgentDeadlineExceeded(asyncio.TimeoutError):
    pass


class Evidence(AsyncCallbackHandler):
    def __init__(self):
        self.tools = []

    async def on_tool_end(self, output, **kwargs):
        if isinstance(output, ToolMessage) and output.status != 'error' and successful(output.content):
            self.tools.append(output)


async def run_react(agent, data, *, timeout_seconds, recursion_limit, llm=None):
    started = time.monotonic()
    reserve = min(float(os.getenv('ANALYSIS_FINAL_RESERVE_SECONDS', '90')), timeout_seconds / 3)
    if not math.isfinite(reserve) or reserve <= 0:
        raise ValueError('收尾预留时间必须为正的有限秒数')
    evidence = Evidence()
    config = {'recursion_limit': recursion_limit}
    if llm is not None:
        config['callbacks'] = [evidence]
    task = asyncio.create_task(agent.ainvoke(data, config=config))
    response = None
    try:
        done, _ = await asyncio.wait({task}, timeout=timeout_seconds-reserve if llm else timeout_seconds)
        if done:
            try:
                response = task.result()
            except asyncio.TimeoutError as error:
                raise RuntimeError('内部工具或模型调用超时，未触发分析总时限') from error
            except GraphRecursionError:
                if llm is None:
                    raise
            if llm is None:
                return response
            if response is not None:
                last = response.get('messages', [])[-1:]
                reason = (last[0].response_metadata.get('finish_reason') or last[0].response_metadata.get('stop_reason')) if last else None
                if reason not in {'length','max_tokens'}:
                    return response
        elif llm is None:
            raise AgentDeadlineExceeded(f'分析总时限已到（{timeout_seconds:g} 秒）')
    finally:
        if not task.done():
            task.cancel()
        await asyncio.gather(task, return_exceptions=True)
    # One bounded, tool-free synthesis. Reuse evidence; never restart retrieval.
    tools = [m for m in (response or {}).get('messages', []) if isinstance(m, ToolMessage)
             and m.status != 'error' and successful(m.content)] or evidence.tools
    if not tools:
        raise ValueError('取数阶段已结束，未取得足以生成分析的有效资料，无法进行收尾生成')
    remaining = timeout_seconds - (time.monotonic()-started)
    if remaining <= 0:
        raise AgentDeadlineExceeded(f'分析总时限已到（{timeout_seconds:g} 秒）')
    from src.utils.observability import trace_scope
    excerpts = '\n\n'.join(f'{m.name or "数据工具"}: {str(m.content)[:2400]}' for m in tools)[:24000]
    original = str(data.get('messages', []))[:7000]
    prompt = [HumanMessage(content=f'原始研究要求：{original}\n已成功取得的真实工具资料（可能只含片段）：\n{excerpts}\n'
              '请直接完成本角色分析，控制在1200个中文字符以内；不再调用工具。只使用上述有证据的数据，'
              '缺失内容明确说明，不作推测补齐。保留关键结论、数据来源和风险，正常结束全文。')]
    with trace_scope('analysis.bounded_synthesis', metadata={'evidence_tools': len(tools)}):
        try:
            final = await asyncio.wait_for(llm.ainvoke(prompt), timeout=remaining)
        except asyncio.TimeoutError as error:
            raise AgentDeadlineExceeded('预留的收尾生成时间已耗尽') from error
        result = {'messages': [*tools, final]}
        extract_analysis_text(result)
        return result
