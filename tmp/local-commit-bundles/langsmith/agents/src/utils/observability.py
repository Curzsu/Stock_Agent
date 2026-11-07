"""Optional LangSmith scopes; native LangChain callbacks record model/tool turns.

Only explicit LANGSMITH_TRACING=true plus a key enables cloud delivery. The
SDK owns batching/sampling and preserves provider usage, including failed turns.
"""
import asyncio
from contextlib import contextmanager, nullcontext
from functools import lru_cache
import logging
import os
import sys
from uuid import uuid4

from langsmith import Client, trace, tracing_context
from langchain_core.tracers.context import tracing_v2_enabled


logger = logging.getLogger(__name__)
_client = None
RESULT_KEYS = {
    "fundamental": "fundamental_analysis",
    "technical": "technical_analysis",
    "value": "value_analysis",
    "news": "news_analysis",
    "summary": "final_report",
}


@lru_cache(maxsize=1)
def get_client():
    """Create the background sender lazily, after the entrypoint loads .env."""
    global _client
    _client = Client(timeout_ms=3000)
    return _client


@contextmanager
def trace_scope(name, *, metadata=None, inputs=None, run_type="chain"):
    enabled = (
        os.getenv("LANGSMITH_TRACING", "false").lower() == "true"
        and bool(os.getenv("LANGSMITH_API_KEY", "").strip())
    )
    client = None
    if enabled:
        try:
            client = get_client()
        except Exception:
            # Misconfiguration of observability must not prevent stock research.
            logger.warning("LangSmith 初始化失败，本次分析关闭追踪。")
            enabled = False
    with tracing_context(enabled=enabled, client=client):
        if not enabled:
            yield None
            return
        try:
            scope = trace(name, run_type=run_type, inputs=inputs or {},
                          metadata=metadata or {}, tags=["finex"])
            run = scope.__enter__()
        except Exception:
            logger.warning("LangSmith 追踪创建失败，本次操作关闭追踪。")
            with tracing_context(enabled=False):
                yield None
            return
        # langchain-core 1.2 defaults an unset project to "default", including
        # inside agent-addressed traces. Pin the scoped native tracer to address
        # routing so its model/tool payloads never mix address + session_name.
        native_scope = tracing_v2_enabled(client=client) if run.address else nullcontext(None)
        with native_scope as tracer:
            if tracer is not None:
                tracer.project_name = None
            error_info = (None, None, None)
            try:
                yield run
            except BaseException:
                # Preserve cancellation and the original business exception even
                # if telemetry fails. Never re-execute the business operation.
                error_info = sys.exc_info()
                raise
            finally:
                try:
                    if run.end_time is None:
                        run.end()
                    scope.__exit__(*error_info)
                except Exception:
                    logger.warning("LangSmith 追踪提交失败。")


def trace_metadata(state):
    data = state.get("data", {})
    source = state.setdefault("metadata", {})
    source.setdefault("analysis_id", str(uuid4()))
    return {key: value for key, value in {
        "analysis_id": source["analysis_id"],
        "stock_code": data.get("stock_code"),
        "company_name": data.get("company_name"),
        "retry": source.get("retry"),
    }.items() if value is not None}


def analysis_trace(state, operation="analysis"):
    return trace_scope(
        f"finex.{operation}", metadata={**trace_metadata(state), "operation": operation},
        inputs={"query": state.get("data", {}).get("query", "")},
    )


def finish_trace(run, result, agent_key=None):
    """Mark returned error dictionaries as failures without changing control flow."""
    if run is None:
        return
    data = (result or {}).get("data", {})
    if agent_key:
        key = RESULT_KEYS[agent_key]
        error_key = "summary_error" if agent_key == "summary" else f"{key}_error"
        errors = {error_key: data[error_key]} if data.get(error_key) else {}
        if not errors and not data.get(key):
            errors = {error_key: "分析未返回有效结果"}
    else:
        errors = {key: value for key, value in data.items()
                  if key in {"summary_error", *(f"{k}_analysis_error" for k in RESULT_KEYS if k != "summary")}
                  and value}
    run.end(outputs={"status": "failed" if errors else "completed", "errors": errors},
            error="; ".join(f"{key}: {value}" for key, value in errors.items()) or None)


async def invoke_agent(agent, state, agent_key):
    with trace_scope(f"finex.agent.{agent_key}",
                     metadata={**trace_metadata(state), "agent": agent_key}) as run:
        result = await agent(state)
        finish_trace(run, result, agent_key)
        return result


async def invoke_workflow(workflow, state):
    with analysis_trace(state) as run:
        result = await workflow.ainvoke(state, config={"metadata": trace_metadata(state)})
        finish_trace(run, result)
        return result


async def flush_traces():
    """Drain only this integration's client, off the event loop, at shutdown."""
    global _client
    if _client is not None:
        try:
            await asyncio.to_thread(_client.close, timeout=5)
        except Exception:
            logger.warning("LangSmith 追踪刷新失败。")
        finally:
            _client = None
            get_client.cache_clear()
