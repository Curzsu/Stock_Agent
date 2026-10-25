"""Validate final model text before treating an analysis as successful."""

from typing import Any

from langchain_core.messages import AIMessage


def require_analysis_text(content: Any) -> str:
    """Normalize text blocks, rejecting absent text and known fallback markers."""
    if isinstance(content, list):
        parts = []
        for block in content:
            if isinstance(block, str):
                parts.append(block.strip())
            elif isinstance(block, dict) and block.get("type") in {"text", "output_text"}:
                if isinstance(block.get("text"), str):
                    parts.append(block["text"].strip())
        content = "\n".join(part for part in parts if part)
    if not isinstance(content, str) or not content.strip():
        raise ValueError("模型未生成有效的分析内容，请重试")
    text = content.strip()
    if text.casefold() in {"no analysis generated.", "not available"}:
        raise ValueError("模型仅返回占位内容，请重试")
    return text


def extract_analysis_text(response: Any) -> str:
    """Accept only a final AI message after all tool calls have finished."""
    messages = response.get("messages") if isinstance(response, dict) else None
    if not isinstance(messages, (list, tuple)) or not messages:
        raise ValueError("模型未返回最终分析消息，请重试")
    final_message = messages[-1]
    if not isinstance(final_message, AIMessage):
        raise ValueError("模型未返回最终分析消息，请重试")
    if final_message.tool_calls or final_message.invalid_tool_calls:
        raise ValueError("模型在工具调用完成前结束，未生成最终分析，请重试")
    reason = final_message.response_metadata.get("finish_reason") or final_message.response_metadata.get("stop_reason")
    if reason in {"length", "max_tokens", "content_filter", "tool_calls", "tool_use", "function_call"}:
        raise ValueError(f"模型输出未完整结束（{reason}），请重试或调整模型输出上限")
    return require_analysis_text(final_message.content)
