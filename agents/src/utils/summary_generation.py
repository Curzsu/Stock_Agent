"""Bounded synthesis recovery, with diagnostics recorded before validation."""
import os
import time

from src.utils.agent_output import extract_analysis_text


def summary_max_tokens():
    value = int(os.getenv("SUMMARY_MAX_TOKENS", "12000"))
    if value <= 0:
        raise ValueError("SUMMARY_MAX_TOKENS 必须大于 0")
    return value


async def generate_summary(llm, messages, execution_logger, model_config):
    """Retry length termination once with a shorter report, never accept fragments.

    The caller must wrap the whole coroutine in one timeout, including retries.
    """
    for attempt, target_chars in enumerate((2400, 1200), start=1):
        instruction = (
            f"篇幅要求：正文控制在 {target_chars} 个中文字符以内。保留要求的章节，"
            "每节只写关键结论和必要数据，避免重复四份原始分析；"
            "压缩时仍保留关键指标和术语的加粗，以及摘要引用、指标表和简短列表，勿压成连续段落；"
            "必须完成风险、建议和分析基准时间后正常结束。"
        )
        if attempt > 1:
            instruction = "上次输出因长度限制被截断。请重新压缩生成完整报告，不要续写残稿。" + instruction
        prompt = [*messages, {"role": "user", "content": instruction}]
        started = time.monotonic()
        response = await llm.ainvoke(prompt)
        metadata = getattr(response, "response_metadata", {})
        reason = metadata.get("finish_reason") or metadata.get("stop_reason")
        # Log even truncated/empty responses, before extract_analysis_text raises.
        execution_logger.log_llm_interaction(
            agent_name="summary_agent",
            interaction_type="summary_generation",
            input_messages=prompt,
            output_content=str(response.content),
            model_config={**model_config, "attempt": attempt, "finish_reason": reason},
            execution_time=time.monotonic() - started,
            token_usage=getattr(response, "usage_metadata", None) or metadata.get("token_usage"),
        )
        if reason in {"length", "max_tokens"} and attempt == 1:
            continue
        return extract_analysis_text({"messages": [response]})
