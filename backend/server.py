"""
FINEX Web Server - FastAPI backend for Financial Analysis AI Agent System

This module provides REST API endpoints for the frontend to interact with
the multi-agent financial analysis system.
"""

import os
import sys

# Fix Windows console encoding for emoji/unicode characters
# This must be done before any output to stdout/stderr
if sys.platform == 'win32':
    sys.stdout.reconfigure(encoding='utf-8', errors='replace')
    sys.stderr.reconfigure(encoding='utf-8', errors='replace')
import re
import shutil
import tempfile
from contextlib import asynccontextmanager
from ipaddress import ip_address
from datetime import date, datetime, timedelta
from typing import Annotated, Optional, Dict, Any, Literal
from pathlib import Path
from uuid import UUID, uuid4

# Add project root and Financial-MCP-Agent to path
project_root = Path(__file__).parent.parent
sys.path.insert(0, str(project_root))
sys.path.insert(0, str(project_root / "agents"))

import asyncio
from fastapi import Depends, FastAPI, Header, HTTPException, Request
from fastapi.exception_handlers import request_validation_exception_handler
from fastapi.exceptions import RequestValidationError
from fastapi.staticfiles import StaticFiles
from fastapi.responses import HTMLResponse, FileResponse, JSONResponse
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel, Field, PrivateAttr, field_validator
import baostock as bs

# Import agent system components
from dotenv import dotenv_values, load_dotenv
from src.utils.api_settings import API_ENV_KEYS, ApiSettings, current_api_settings, current_summary_mode, use_api_settings
# Load .env from agents folder
env_path = Path(__file__).parent.parent / "agents" / ".env"
load_dotenv(env_path, override=True)

# LangGraph imports
from src.utils.workflow_builder import build_workflow
from src.utils.research_scope import research_scope
from src.utils.observability import analysis_trace, flush_traces, invoke_agent, invoke_workflow
from langchain_openai import ChatOpenAI
from langchain_core.messages import HumanMessage

# Import agents (using src.* after adding agents to path)
from src.agents.fundamental_agent import fundamental_agent
from src.agents.technical_agent import technical_agent
from src.agents.value_agent import value_agent
from src.agents.news_agent import news_agent
from src.agents.summary_agent import summary_agent

# Import state definition
from src.utils.state_definition import AgentState

# Import baostock thread-safe helper (P0-2: 修复全局登录并发竞态)
from src.utils.baostock_helper import BaostockBlacklistedError, BaostockDataError, safe_query

# Import shared PDF path derivation (P2-6: 消除三处重复的路径推断逻辑)
from src.utils.pdf_converter import derive_pdf_path, get_pdf_status, is_pdf_generation_running

# Import shared stock info extractor (P2-3: 合并 main.py 与 server.py 两套 extract_stock_info)
from src.utils.stock_extractor import extract_stock_info, COMPANY_CODE_MAP
from src.utils.agent_output import require_analysis_text
from backend.market_data import fetch_stock_market
from backend.accounts import SESSION_ERRORS, ActiveSession, require_session, require_session_write, router as session_router
from backend.tasks import ACTIVE_STATUSES, RunnerReplaced, TaskDatabaseError, TaskStore
from backend.api_models import (
    AnalysisCreated, AnalysisDeleted, AnalysisHistory, AnalysisPartial, AnalysisReport,
    AnalysisRetry, AnalysisStatusResponse, ApiError, IndexMarketResponse, MarketError,
    PdfError, StockMarketResponse,
)

# Import MCP cleanup function
from src.tools.mcp_client import close_mcp_client_sessions

# Profile values are literal, including a dollar sign in a provider credential.
PROFILE_ENV_KEY = "FINEX_API_ACTIVE_PROFILE"
if os.getenv(PROFILE_ENV_KEY):
    settings = dotenv_values(env_path, interpolate=False)
    os.environ.update({key: settings[key] for key in API_ENV_KEYS if settings.get(key) is not None})

# 整个分析工作流的总超时（秒）。4 个分析 Agent 并行各最多
# REACT_TIMEOUT_SECONDS(480s)，随后 summary Agent 再最多 480s，
# 因此整体预算按两阶段上限 + 余量取 1200s，可通过环境变量覆盖。
# 兜底保证工作流一定在有限时间内结束，避免 session 永久停在
# "running" 导致前端分析页无限轮询卡死。
WORKFLOW_TIMEOUT_SECONDS = float(os.getenv("WORKFLOW_TIMEOUT_SECONDS", "1200"))

# 工作流启动前 baostock 股票校验的单次超时（秒）。baostock 是远程行情
# 数据服务，服务器无响应时 bs.login/query 会无限阻塞（socket 层超时对其
# 无效，已实测）。若不加限制，分析会永远卡在"等待中"（校验阶段在设置
# progress=running 之前执行）。超时后置为明确的错误状态，而非无限等待。
BAOSTOCK_TIMEOUT_SECONDS = float(os.getenv("BAOSTOCK_TIMEOUT_SECONDS", "30"))

# ============================================================================
# FastAPI Application Setup
# ============================================================================

@asynccontextmanager
async def lifespan(application: FastAPI):
    store = TaskStore.from_environment() if os.getenv("DATABASE_URL") else None
    runner = None
    started = False
    try:
        if store is not None:
            runner = await asyncio.to_thread(store.claim_runner)
            pending_cleanup = await asyncio.to_thread(store.recover)
            for entry in pending_cleanup:
                try:
                    await asyncio.to_thread(store.finish_cleanup, entry["owner_id"], entry["id"], delete_task_directory)
                except HTTPException:
                    print(f"Warning: unfinished report cleanup for {entry['id']}")
        application.state.task_store = store
        started = True
        yield
    finally:
        try:
            if started:
                if pending_admissions:
                    await asyncio.gather(*pending_admissions, return_exceptions=True)
                jobs = tuple(managed_jobs)
                for job in jobs:
                    job.cancel()
                await asyncio.gather(*jobs, return_exceptions=True)
                application.state.task_store = None
                await _shutdown_cleanup_mcp()
        finally:
            if runner is not None:
                await asyncio.to_thread(runner.close)


app = FastAPI(
    title="FINEX API",
    description="Financial Analysis AI Agent System API",
    version="1.0.0",
    lifespan=lifespan,
)

# Browser sessions use the same-origin API, including behind the Vite proxy.
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=False,
    allow_methods=["*"],
    allow_headers=["*"],
)
app.include_router(session_router)


@app.middleware("http")
async def mark_private_responses(request: Request, call_next):
    response = await call_next(request)
    path = request.url.path
    if path in {"/api/session", "/api/analyze", "/api/history"} or path.startswith((
        "/api/status/", "/api/analysis/", "/api/result/", "/api/report-pdf/", "/api/history/",
    )):
        response.headers["Cache-Control"] = "no-store"
    return response


@app.exception_handler(RequestValidationError)
async def validate_request_response(request: Request, exc: RequestValidationError):
    if request.url.path == "/api/session" and request.method == "POST":
        return JSONResponse({"detail": "用户名或密码格式无效"}, status_code=422)
    return await request_validation_exception_handler(request, exc)


async def _shutdown_cleanup_mcp():
    """应用关停时统一清理 MCP 客户端缓存状态。

    MCP 工具跨请求复用同一个长驻 stdio 会话，故障后由客户端重建。
    应用关闭时在会话所属任务中退出上下文，无需逐请求清理。
    """
    try:
        await close_mcp_client_sessions()
    except Exception as e:
        print(f"Warning: MCP cleanup error on shutdown: {e}")
    await flush_traces()

# ============================================================================
# Data Models
# ============================================================================

AGENT_RESULT_KEYS = {
    "fundamental": ("fundamental_analysis", "fundamental_analysis_error"),
    "technical": ("technical_analysis", "technical_analysis_error"),
    "value": ("value_analysis", "value_analysis_error"),
    "news": ("news_analysis", "news_analysis_error"),
    "summary": ("final_report", "summary_error"),
}


def new_agent_details() -> Dict[str, Dict[str, Any]]:
    """Return isolated, JSON-safe lifecycle state for every analysis agent."""
    return {
        key: {
            "status": "waiting",
            "started_at": None,
            "completed_at": None,
            "execution_time_ms": None,
            "summary": "",
            "result_available": False,
            "error": None,
        }
        for key in AGENT_RESULT_KEYS
    }


def summarize_agent_text(text: str, limit: int = 180) -> str:
    """Extract a compact plain-text preview from a Markdown analysis result."""
    for block in re.split(r"\n\s*\n", text or ""):
        cleaned = re.sub(r"^[#>*\-\s]+", "", block).strip()
        cleaned = re.sub(r"[*_`]+", "", cleaned).strip()
        if len(cleaned) >= 8:
            return cleaned[:limit] + ("…" if len(cleaned) > limit else "")
    return ""


AGENT_TASK_LABELS = {
    "fundamental": "正在分析财务表现与经营质量",
    "technical": "正在分析价格趋势与关键价位",
    "value": "正在比较历史估值分位与行业水平",
    "news": "正在检索新闻、公告与风险事件",
    "summary": "正在汇总四路研究并生成综合结论",
}


def mark_agent_status(session, agent_key: str, status: str) -> None:
    """Record an agent lifecycle transition without inventing percentages."""
    now = datetime.now().isoformat()
    detail = session.agent_details[agent_key]
    if status == "running":
        detail.update({
            "status": "running",
            "started_at": now,
            "completed_at": None,
            "execution_time_ms": None,
            "error": None,
        })
        session.progress[agent_key] = "running"
        session.current_task = AGENT_TASK_LABELS[agent_key]
    elif status == "completed" and detail["status"] != "failed":
        detail["status"] = "completed"
        detail["completed_at"] = detail["completed_at"] or now
        session.progress[agent_key] = "completed"


def record_agent_result(session, agent_key: str, result: dict, completed_at=None) -> None:
    """Persist one agent result as soon as the workflow node finishes."""
    result_key, error_key = AGENT_RESULT_KEYS[agent_key]
    data = dict((result or {}).get("data", {}))
    detail = session.agent_details[agent_key]
    finished = completed_at or datetime.now().isoformat()
    detail["completed_at"] = finished

    if detail.get("started_at"):
        start = datetime.fromisoformat(detail["started_at"])
        end = datetime.fromisoformat(finished)
        detail["execution_time_ms"] = max(
            0,
            int((end - start).total_seconds() * 1000),
        )

    error = data.get(error_key)
    if not error:
        try:
            text = require_analysis_text(data.get(result_key))
        except ValueError as exc:
            error = str(exc)
    if error:
        detail.update({
            "status": "failed",
            "error": str(error),
            "summary": "",
            "result_available": False,
        })
        session.progress[agent_key] = "failed"
        session.partial_results.pop(result_key, None)
        return

    session.partial_results[result_key] = text
    detail.update({
        "status": "completed",
        "error": None,
        "summary": summarize_agent_text(text),
        "result_available": bool(text),
    })
    session.progress[agent_key] = "completed"


def rebuild_session_result(session, data: Optional[Dict[str, Any]] = None) -> None:
    """Rebuild the public report payload from durable session data."""
    merged = {**session.initial_data, **session.partial_results, **(data or {})}
    report_path = merged.get("report_path", "")
    pdf_path = merged.get("pdf_path")
    pdf_available = False
    if report_path:
        expected_pdf_path = derive_pdf_path(report_path)
        pdf_available = os.path.exists(expected_pdf_path)
        if pdf_available and not pdf_path:
            pdf_path = expected_pdf_path

    stock_code = str(merged.get("stock_code", "") or "")
    public_stock_code = stock_code.split(".", 1)[-1] if "." in stock_code else stock_code
    missing_dimensions = [
        key
        for key in ("fundamental", "technical", "value", "news")
        if session.agent_details[key]["status"] == "failed"
    ]
    session.result = {
        "company_name": session.company_name or merged.get("company_name", ""),
        "stock_code": public_stock_code,
        "query": session.query or merged.get("query", ""),
        "fundamental_analysis": merged.get("fundamental_analysis", ""),
        "technical_analysis": merged.get("technical_analysis", ""),
        "value_analysis": merged.get("value_analysis", ""),
        "news_analysis": merged.get("news_analysis", ""),
        "final_report": merged.get("final_report", ""),
        "analysis_date": merged.get("current_date", ""),
        "report_path": report_path,
        "pdf_path": pdf_path or "",
        "pdf_available": pdf_available,
        "missing_dimensions": missing_dimensions,
    }


def finish_analysis_session(session) -> None:
    """A failed synthesis is an error even when all four dimensions succeeded."""
    summary = session.agent_details["summary"]
    if summary["status"] == "failed":
        session.status = "error"
        session.error = f"汇总报告生成失败，可重试汇总（已完成的分析会保留）：{summary['error']}"
    else:
        session.status = "degraded" if any(
            session.agent_details[key]["status"] == "failed"
            for key in ("fundamental", "technical", "value", "news")
        ) else "completed"
        session.error = None
    session.end_time = datetime.now().isoformat()
    session.current_task = None


RETRYABLE_AGENTS = {
    "fundamental": fundamental_agent,
    "technical": technical_agent,
    "value": value_agent,
    "news": news_agent,
}


async def retry_agent_and_summary(
    analysis_id: str,
    agent_key: str,
    selected_agent=None,
    summarizer=None,
) -> None:
    session = analysis_sessions[analysis_id]
    state = AgentState(messages=[], data=session.initial_data, metadata=report_metadata_for(session, retry=agent_key))
    async with research_scope():
        with analysis_trace(state, operation="retry") as run:
            await _retry_agent_and_summary(analysis_id, agent_key, selected_agent, summarizer)
            if run is not None:
                errors = [f"{key}: {detail.get('error') or '分析未返回有效结果'}"
                          for key, detail in session.agent_details.items() if detail["status"] == "failed"]
                run.end(outputs={"status": session.status},
                        error=session.error or "; ".join(errors) or None)


async def _retry_agent_and_summary(
    analysis_id: str,
    agent_key: str,
    selected_agent=None,
    summarizer=None,
) -> None:
    """Rerun one failed dimension, then rebuild the synthesis in place."""
    session = analysis_sessions[analysis_id]
    summary_fn = summarizer or summary_agent
    active_agent = agent_key
    try:
        if agent_key != "summary":
            agent_fn = selected_agent or RETRYABLE_AGENTS[agent_key]
            state = AgentState(
                messages=[],
                data={**session.initial_data, **session.partial_results},
                metadata=report_metadata_for(session, retry=agent_key),
            )
            if session.agent_details[agent_key]["status"] != "running":
                mark_agent_status(session, agent_key, "running")
            agent_result = await invoke_agent(agent_fn, state, agent_key)
            record_agent_result(session, agent_key, agent_result)
            if session.agent_details[agent_key]["status"] == "failed":
                finish_analysis_session(session)
                return
            await checkpoint_analysis(session)

        summary_data = {**session.initial_data, **session.partial_results}
        for key in RETRYABLE_AGENTS:
            detail = session.agent_details[key]
            if detail["status"] == "failed":
                summary_data[AGENT_RESULT_KEYS[key][1]] = detail["error"] or "分析不可用"
        summary_state = AgentState(
            messages=[],
            data=summary_data,
            metadata=report_metadata_for(session, retry=agent_key),
        )
        active_agent = "summary"
        mark_agent_status(session, "summary", "running")
        await checkpoint_analysis(session)
        summary_result = await invoke_agent(summary_fn, summary_state, "summary")
        record_agent_result(session, "summary", summary_result)
        rebuild_session_result(session, (summary_result or {}).get("data", {}))
        finish_analysis_session(session)
    except Exception as exc:
        error_key = AGENT_RESULT_KEYS[active_agent][1]
        record_agent_result(session, active_agent, {"data": {error_key: str(exc) or type(exc).__name__}})
        finish_analysis_session(session)

class AnalyzeRequest(BaseModel):
    """Request model for analysis endpoint"""
    query: str

    @field_validator('query')
    @classmethod
    def validate_query(cls, v: str) -> str:
        v = v.strip()
        if not v:
            raise ValueError('查询内容不能为空')
        if len(v) < 2:
            raise ValueError('请输入至少2个字符的公司名称或股票代码')
        # 纯数字但不是5-6位
        if v.isdigit() and (len(v) < 5 or len(v) > 6):
            raise ValueError('股票代码应为5-6位数字，如 600519')
        # 纯特殊符号
        import re
        if re.match(r'^[^a-zA-Z0-9\u4e00-\u9fa5]+$', v):
            raise ValueError('请输入有效的公司名称或股票代码')
        return v

class AnalysisStatus(BaseModel):
    """Status model for tracking analysis progress"""
    analysis_id: str
    owner_id: UUID | None = None
    status: str  # 'pending', 'running', 'completed', 'error'
    progress: Dict[str, str]  # agent_name -> status
    start_time: Optional[str] = None
    end_time: Optional[str] = None
    result: Optional[Dict[str, Any]] = None
    error: Optional[str] = None
    query: Optional[str] = None
    company_name: Optional[str] = None
    agent_details: Dict[str, Dict[str, Any]] = Field(default_factory=new_agent_details)
    partial_results: Dict[str, Any] = Field(default_factory=dict)
    current_task: Optional[str] = None
    initial_data: Dict[str, Any] = Field(default_factory=dict)
    api_profile: Optional[str] = None
    _api_settings: ApiSettings = PrivateAttr(default_factory=current_api_settings)
    _summary_mode: str = PrivateAttr(default_factory=current_summary_mode)
    _store: TaskStore | None = PrivateAttr(default=None)
    _checkpoint_lock: asyncio.Lock = PrivateAttr(default_factory=asyncio.Lock)


class ApiConfigRequest(BaseModel):
    """Request model for API config endpoint (所有字段可选,未传则保留原值)"""
    api_key: Optional[str] = None
    base_url: Optional[str] = None
    model: Optional[str] = None


def require_local_config_access(request: Request) -> None:
    """Configuration belongs to the local operator, including browser requests."""
    require_local_page_access(request, "API 配置仅允许通过本机页面访问")


def require_local_history_access(request: Request) -> None:
    """Only the local operator may permanently delete generated reports."""
    require_local_page_access(request, "删除研报仅允许通过本机页面操作")


def require_local_page_access(request: Request, message: str) -> None:
    try:
        local_client = request.client is not None and ip_address(request.client.host).is_loopback
    except ValueError:
        local_client = False
    origin = request.headers.get("origin")
    if (
        not local_client
        or request.url.hostname not in {"localhost", "127.0.0.1", "::1"}
        or (origin is not None and origin != str(request.base_url).rstrip("/"))
    ):
        raise HTTPException(status_code=403, detail=message)


def validate_config_destination(config: ApiConfigRequest, saved: ApiSettings) -> None:
    """Never carry a saved credential to a newly supplied service URL."""
    if (
        config.base_url is not None
        and config.base_url.rstrip("/") != saved.base_url.rstrip("/")
        and saved.api_key
        and not config.api_key
    ):
        raise HTTPException(status_code=422, detail="更换 Base URL 时请重新输入 API Key")


def mask_api_key(key: str) -> str:
    """脱敏 API key:保留前3后4,中间用 *** 代替。短于7位则全掩码。"""
    if not key:
        return ""
    if len(key) <= 7:
        return "***"
    return f"{key[:3]}***{key[-4:]}"


def update_env_file(path, updates: dict) -> None:
    """
    更新 .env 文件中指定 key 的值(原地替换,缺则追加)。
    保留注释和空行。只更新 updates 里出现的 key。

    Args:
        path: .env 文件路径
        updates: {env_key: new_value} 只含需要更新的项
    """
    path = Path(path)
    remaining = dict(updates)  # 待写入的 key(文件里没有的会追加)
    out_lines = []

    if os.path.exists(path):
        with open(path, "r", encoding="utf-8") as f:
            for line in f:
                stripped = line.strip()
                # 跳过空行和注释,原样保留
                if not stripped or stripped.startswith("#"):
                    out_lines.append(line)
                    continue
                # 解析 KEY=VALUE
                if "=" in stripped:
                    key = stripped.split("=", 1)[0].strip().removeprefix("export ").strip()
                    if key in updates:
                        if key in remaining:
                            out_lines.append(_env_assignment(key, remaining.pop(key)))
                        continue
                out_lines.append(line)

    # 文件里没有的 key,追加到末尾
    if remaining and out_lines and not out_lines[-1].endswith("\n"):
        out_lines.append("\n")
    out_lines.extend(_env_assignment(key, value) for key, value in remaining.items())

    temporary = None
    try:
        with tempfile.NamedTemporaryFile(mode="w", encoding="utf-8", dir=path.parent,
                                         prefix=".env.", suffix=".local", delete=False) as stream:
            temporary = Path(stream.name)
            stream.writelines(out_lines)
        temporary.replace(path)
    finally:
        if temporary is not None:
            temporary.unlink(missing_ok=True)


def _env_assignment(key: str, value: str) -> str:
    if re.fullmatch(r"[\w./:+@%=-]*", value):
        return f"{key}={value}\n"
    escaped = value.replace("\\", "\\\\").replace("'", "\\'")
    return f"{key}='{escaped}'\n"


# ============================================================================
# In-memory storage for analysis sessions
# ============================================================================

analysis_sessions: Dict[str, AnalysisStatus] = {}
managed_jobs: set[asyncio.Task] = set()
pending_admissions: set[asyncio.Task] = set()
STORAGE_ERRORS = {**SESSION_ERRORS, 500: {"model": ApiError}}
TASK_ERRORS = {**STORAGE_ERRORS, 404: {"model": ApiError}}
ADMISSION_ERRORS = {409: {"model": ApiError}, 429: {"model": ApiError}}


def get_task_store(request: Request) -> TaskStore:
    store = getattr(request.app.state, "task_store", None)
    if store is None:
        raise HTTPException(503, "任务数据库未配置或服务尚未就绪")
    return store


TaskStorage = Annotated[TaskStore | None, Depends(get_task_store)]


def public_analysis_error(session: AnalysisStatus) -> str | None:
    error = session.error
    if error and error.startswith("汇总报告生成失败"):
        return "汇总报告生成失败，可重试汇总（已完成的分析会保留）。"
    if error and error.startswith("行情数据服务（baostock）"):
        return error.partition("：")[0]
    return error


def public_agent_details(session: AnalysisStatus) -> dict:
    return {
        key: {**detail, "error": "该维度未取得有效结果，可在研究结束后重试。" if detail.get("error") else None}
        for key, detail in session.agent_details.items()
    }


def task_snapshot(session: AnalysisStatus) -> dict:
    snapshot = session.model_dump(mode="json", exclude={"analysis_id", "owner_id", "status"})
    snapshot.update(error=public_analysis_error(session), agent_details=public_agent_details(session))
    if snapshot["result"] is not None:
        for key in ("report_path", "pdf_path", "pdf_available", "pdf_status"):
            snapshot["result"].pop(key, None)
    return snapshot


async def task_db_call(call, *args):
    """Let an in-flight transaction finish before releasing the executor on shutdown."""
    transaction = asyncio.create_task(asyncio.to_thread(call, *args))
    try:
        return await asyncio.shield(transaction)
    except asyncio.CancelledError:
        await asyncio.gather(transaction, return_exceptions=True)
        raise


async def checkpoint_analysis(session: AnalysisStatus, report=None):
    if session._store is not None:
        async with session._checkpoint_lock:
            await task_db_call(session._store.checkpoint, session.analysis_id, session.owner_id, session.status,
                               task_snapshot(session), report)


def report_state(markdown_path: str) -> str:
    pdf = Path(derive_pdf_path(markdown_path))
    if pdf.is_file() and pdf.stat().st_size:
        return "ready"
    if is_pdf_generation_running(markdown_path):
        return "pending"
    return "failed" if get_pdf_status(markdown_path)["status"] == "failed" else "unavailable"


def publish_report_metadata(session: AnalysisStatus):
    if session.status not in {"completed", "degraded"} or not session.result:
        return None
    report_path = session.result.get("report_path")
    if not report_path:
        return None
    store = session._store
    report_date = session.result.get("analysis_date") or None
    return (
        session.result.get("stock_code", ""), date.fromisoformat(report_date) if report_date is not None else None,
        store.relative_path(session.analysis_id, report_path),
        store.relative_path(session.analysis_id, derive_pdf_path(report_path)), report_state(report_path),
    )


async def retry_database_write(call, *args):
    while True:
        try:
            return await call(*args)
        except TaskDatabaseError as exc:
            if not exc.retryable:
                raise
            await asyncio.sleep(1)


async def run_managed_job(session: AnalysisStatus, operation, *args):
    report = None
    try:
        try:
            with use_api_settings(session._api_settings, summary_mode=session._summary_mode):
                await asyncio.wait_for(operation(session.analysis_id, *args),
                                       timeout=WORKFLOW_TIMEOUT_SECONDS + 2 * BAOSTOCK_TIMEOUT_SECONDS)
            if session.status in ACTIVE_STATUSES:
                raise RuntimeError("研究流程未返回终态")
            report = publish_report_metadata(session)
        except Exception as exc:
            print(f"Warning: analysis {session.analysis_id} failed ({type(exc).__name__})")
            session.status = "error"
            session.error = "研究执行失败，请查看本机服务日志后重试。"
            session.end_time = datetime.now().isoformat()
            session.current_task = None
        try:
            await retry_database_write(checkpoint_analysis, session, report)
        except TaskDatabaseError as exc:
            print(f"Warning: analysis {session.analysis_id} publication failed ({type(exc.__cause__).__name__})")
            await retry_database_write(task_db_call, session._store.fail_checkpoint, session.analysis_id, session.owner_id)
            return
    except RunnerReplaced:
        return
    finally:
        if analysis_sessions.get(session.analysis_id) is session:
            analysis_sessions.pop(session.analysis_id)

    if report is not None and report[-1] == "pending":
        markdown_path = str(session._store.artifact_path(session.analysis_id, report[2]))
        while is_pdf_generation_running(markdown_path):
            await asyncio.sleep(0.5)
        try:
            await retry_database_write(task_db_call, session._store.update_pdf, session.analysis_id,
                                       report[2], report_state(markdown_path))
        except RunnerReplaced:
            return


def launch_job(session: AnalysisStatus, operation, *args):
    analysis_sessions[session.analysis_id] = session
    if session._store is None:
        with use_api_settings(session._api_settings, summary_mode=session._summary_mode):
            asyncio.create_task(operation(session.analysis_id, *args))
        return
    task = asyncio.create_task(run_managed_job(session, operation, *args))
    managed_jobs.add(task)
    task.add_done_callback(managed_jobs.discard)


async def complete_admission(operation):
    task = asyncio.create_task(operation)
    pending_admissions.add(task)
    task.add_done_callback(pending_admissions.discard)
    return await asyncio.shield(task)


def report_metadata_for(session: AnalysisStatus, **extra) -> dict:
    metadata = {"analysis_id": session.analysis_id, **extra}
    if session._store is not None:
        metadata["report_dir"] = str(session._store.task_directory(session.analysis_id))
    return metadata


async def require_owned_analysis(
    analysis_id: str, principal: Annotated[ActiveSession, Depends(require_session)], store: TaskStorage,
) -> AnalysisStatus:
    if store is not None:
        return AnalysisStatus.model_validate(await task_db_call(store.get, principal.user_id, analysis_id))
    session = analysis_sessions.get(analysis_id)
    if session is None or session.owner_id != principal.user_id:
        raise HTTPException(status_code=404, detail="Analysis not found")
    return session

# ============================================================================
# Helper Functions
# ============================================================================


def lookup_stock_code_by_name(company_name: str) -> tuple:
    """
    用 baostock 根据公司名称查找股票代码（在线查找，覆盖所有A股）。
    返回 (stock_code: str or None, stock_name: str or None)

    使用进程级单例登录 + 互斥锁，避免并发请求互相踢掉 baostock 全局 session。
    """
    rs = safe_query(lambda: bs.query_stock_basic(code_name=company_name))
    if rs.error_code != '0':
        raise BaostockDataError(f"baostock 股票名称查询失败 ({rs.error_code}): {rs.error_msg}")

    while rs.next():
        row = rs.get_row_data()
        code_full = row[rs.fields.index('code')]
        name = row[rs.fields.index('code_name')]
        if name == company_name:
            pure_code = code_full.split('.')[1] if '.' in code_full else code_full
            return pure_code, name

    return None, None

def verify_stock_code_exists(stock_code: str) -> tuple:
    """
    用 baostock 验证股票代码是否真实存在。
    返回 (exists: bool, stock_name: str or None)

    使用进程级单例登录 + 互斥锁，避免并发请求互相踢掉 baostock 全局 session。
    """
    rs = safe_query(lambda: bs.query_stock_basic(code=stock_code))
    if rs.error_code != '0':
        raise BaostockDataError(f"baostock 股票代码校验失败 ({rs.error_code}): {rs.error_msg}")
    if rs.next():
        name = rs.get_row_data()[rs.fields.index('code_name')] if 'code_name' in rs.fields else None
        return True, name
    return False, None

async def run_analysis_workflow(analysis_id: str, query: str):
    """Run the full analysis workflow in background"""
    session = analysis_sessions[analysis_id]
    session.status = "running"
    session.start_time = datetime.now().isoformat()

    try:
        await checkpoint_analysis(session)
        # Extract stock info
        company_name, stock_code = extract_stock_info(query)
        session.company_name = company_name or query

        # 校验：无法识别有效的公司名称或股票代码
        if not company_name and not stock_code:
            session.status = "error"
            session.error = f"无法识别查询内容「{query}」，请输入有效的公司名称或股票代码。"
            session.end_time = datetime.now().isoformat()
            return

        # 校验：提取到公司名但无法匹配到股票代码，尝试用 baostock 在线查找
        if company_name and not stock_code:
            try:
                stock_code, real_name = await asyncio.wait_for(
                    asyncio.to_thread(lookup_stock_code_by_name, company_name),
                    timeout=BAOSTOCK_TIMEOUT_SECONDS
                )
            except asyncio.TimeoutError:
                session.status = "error"
                session.error = f"行情数据服务（baostock）连接超时，无法查询股票代码，请检查网络后重试。"
                session.end_time = datetime.now().isoformat()
                return
            if stock_code:
                if real_name:
                    company_name = real_name
                    session.company_name = company_name
            else:
                session.status = "error"
                session.error = f"未找到「{company_name}」对应的股票代码，请确认公司名称是否正确，或直接输入股票代码（如 600519）。"
                session.end_time = datetime.now().isoformat()
                return

        # 校验：纯数字股票代码的格式合法性（A股首位只能是0/3/6）
        if stock_code and stock_code.isdigit() and stock_code[0] not in ('0', '3', '6'):
            session.status = "error"
            session.error = f"股票代码「{stock_code}」不是有效的A股代码。沪市以6开头，深市以0或3开头。"
            session.end_time = datetime.now().isoformat()
            return

        # 用 baostock 验证股票代码是否真实存在（最终防线）
        full_code = f"{'sh' if stock_code.startswith('6') else 'sz'}.{stock_code}"
        try:
            exists, real_name = await asyncio.wait_for(
                asyncio.to_thread(verify_stock_code_exists, full_code),
                timeout=BAOSTOCK_TIMEOUT_SECONDS
            )
        except asyncio.TimeoutError:
            session.status = "error"
            session.error = f"行情数据服务（baostock）连接超时，无法校验股票代码，请检查网络后重试。"
            session.end_time = datetime.now().isoformat()
            return
        if not exists:
            session.status = "error"
            session.error = f"股票代码「{full_code}」不存在或已退市，请确认后重试。"
            session.end_time = datetime.now().isoformat()
            return
        # 如果 baostock 返回了真实名称，更新到数据中
        if real_name and (not company_name or company_name == query):
            company_name = real_name
            session.company_name = company_name

        # Get current time info
        current_datetime = datetime.now()
        current_date_cn = current_datetime.strftime("%Y年%m月%d日")
        current_date_en = current_datetime.strftime("%Y-%m-%d")
        current_weekday_cn = ["星期一", "星期二", "星期三", "星期四", "星期五", "星期六", "星期日"][current_datetime.weekday()]
        current_time = current_datetime.strftime("%H:%M:%S")
        current_time_info = f"{current_date_cn} ({current_date_en}) {current_weekday_cn} {current_time}"

        # Prepare initial state
        initial_data = {
            "query": query,
            "current_date": current_date_en,
            "current_date_cn": current_date_cn,
            "current_time": current_time,
            "current_weekday_cn": current_weekday_cn,
            "current_time_info": current_time_info,
            "analysis_timestamp": current_datetime.isoformat()
        }

        if company_name:
            initial_data["company_name"] = company_name

        if stock_code:
            if stock_code.startswith('6'):
                initial_data["stock_code"] = f"sh.{stock_code}"
            elif stock_code.startswith('0') or stock_code.startswith('3'):
                initial_data["stock_code"] = f"sz.{stock_code}"
            else:
                initial_data["stock_code"] = stock_code

        session.initial_data = dict(initial_data)

        initial_state = AgentState(
            messages=[],
            data=initial_data,
            metadata=report_metadata_for(session)
        )

        # Build workflow（共享工厂，与 main.py 共用同一拓扑）
        async def _progress_cb(agent_key, status):
            mark_agent_status(session, agent_key, status)
            await checkpoint_analysis(session)

        async def _result_cb(agent_key, result):
            record_agent_result(session, agent_key, result)
            await checkpoint_analysis(session)

        app_workflow = build_workflow(
            fundamental_agent=fundamental_agent,
            technical_agent=technical_agent,
            value_agent=value_agent,
            news_agent=news_agent,
            summary_agent=summary_agent,
            progress_callback=_progress_cb,
            result_callback=_result_cb,
        )

        # Update progress for each agent
        session.progress = {
            "fundamental": "running",
            "technical": "running",
            "value": "running",
            "news": "running",
            "summary": "waiting"
        }
        await checkpoint_analysis(session)

        # Execute workflow
        # 加总超时兜底：即使某个环节（LLM 调用、MCP/baostock 工具、ReAct 死循环）
        # 意外挂起，也能强制工作流结束，session 一定进入终态，前端不会永久卡住。
        # 超时后抛 TimeoutError 由下方 except 捕获置为 error。
        final_state = await asyncio.wait_for(
            invoke_workflow(app_workflow, initial_state),
            timeout=WORKFLOW_TIMEOUT_SECONDS
        )

        # Extract results
        if final_state and final_state.get("data"):
            data = final_state["data"]
            rebuild_session_result(session, data)
        finish_analysis_session(session)

    except asyncio.TimeoutError:
        session.status = "error"
        session.error = f"分析超时（超过 {WORKFLOW_TIMEOUT_SECONDS:.0f} 秒），请稍后重试。"
        session.end_time = datetime.now().isoformat()

    except BaostockBlacklistedError as e:
        session.status = "error"
        session.error = f"行情数据服务（baostock）访问已暂停：{e}"
        session.end_time = datetime.now().isoformat()

    except BaostockDataError as e:
        session.status = "error"
        session.error = f"行情数据服务（baostock）暂时不可用，请稍后重试：{e}"
        session.end_time = datetime.now().isoformat()

    except Exception as exc:
        print(f"Warning: analysis {analysis_id} failed ({type(exc).__name__})")
        session.status = "error"
        session.error = "研究执行失败，请查看本机服务日志后重试。"
        session.end_time = datetime.now().isoformat()

    finally:
        # MCP 是跨请求共享的长驻会话；不能在此关闭其他分析仍在使用的连接。
        # 客户端负责故障恢复，FastAPI shutdown 负责最终清理。
        pass

# ============================================================================
# API Endpoints
# ============================================================================

@app.get("/", response_class=HTMLResponse)
async def serve_frontend():
    """Serve the main frontend HTML page"""
    frontend_path = Path(__file__).parent.parent / "frontend" / "index.html"
    if frontend_path.exists():
        return HTMLResponse(content=frontend_path.read_text(encoding="utf-8"))
    raise HTTPException(status_code=404, detail="Frontend not found")

@app.post("/api/analyze", response_model=AnalysisCreated, responses={**STORAGE_ERRORS, **ADMISSION_ERRORS})
async def start_analysis(
    request: AnalyzeRequest, principal: ActiveSession = Depends(require_session_write), store: TaskStorage = None,
    idempotency_key: Annotated[str | None, Header(alias="Idempotency-Key", pattern=r"^[!-~]{1,128}$")] = None,
):
    """Start a new analysis task"""
    analysis_id = uuid4().hex

    # Create session
    session = AnalysisStatus(
        analysis_id=analysis_id,
        owner_id=principal.user_id,
        status="pending",
        progress={
            "fundamental": "waiting",
            "technical": "waiting",
            "value": "waiting",
            "news": "waiting",
            "summary": "waiting"
        },
        query=request.query,
        api_profile=active_profile(),
    )

    async def admit():
        if store is not None:
            task_id, created = await task_db_call(
                store.create, analysis_id, principal.user_id, idempotency_key, request.query, task_snapshot(session),
                session.api_profile, (*session._api_settings, session._summary_mode),
            )
            if not created:
                return task_id
            session._store = store
        launch_job(session, run_analysis_workflow, request.query)
        return analysis_id

    persisted_id = await complete_admission(admit()) if store is not None else await admit()

    return {
        "analysis_id": persisted_id,
        "status": "started",
        "message": f"Analysis started for: {request.query}"
    }

@app.get("/api/status/{analysis_id}", response_model=AnalysisStatusResponse, responses=TASK_ERRORS)
async def get_analysis_status(session: AnalysisStatus = Depends(require_owned_analysis)):
    """Get the current status of an analysis"""
    return {
        "analysis_id": session.analysis_id,
        "status": session.status,
        "progress": session.progress,
        "start_time": session.start_time,
        "end_time": session.end_time,
        "error": public_analysis_error(session),
        "agent_details": public_agent_details(session),
        "current_task": session.current_task,
        "company_name": session.company_name,
        "stock_code": session.initial_data.get("stock_code"),
    }


@app.get("/api/analysis/{analysis_id}/partial", response_model=AnalysisPartial,
         response_model_exclude_unset=True, responses=TASK_ERRORS)
async def get_partial_results(session: AnalysisStatus = Depends(require_owned_analysis)):
    """Return analysis dimensions that have completed so far."""
    return {"analysis_id": session.analysis_id, "results": session.partial_results}


def prepare_analysis_retry(session: AnalysisStatus, agent_key: str) -> None:
    if agent_key not in {*RETRYABLE_AGENTS, "summary"}:
        raise HTTPException(status_code=422, detail="Unknown analysis agent")
    if session.status not in {"completed", "degraded", "error"}:
        raise HTTPException(status_code=409, detail="Wait for the current workflow to finish before retrying")
    if any(
        detail.get("status") == "running"
        for detail in session.agent_details.values()
    ):
        raise HTTPException(status_code=409, detail="Another analysis task is still running")
    if session.agent_details[agent_key]["status"] != "failed":
        raise HTTPException(status_code=409, detail="This analysis dimension is not failed")
    if agent_key == "summary" and (
        not session.initial_data or not session.partial_results or any(
            session.agent_details[key]["status"] not in {"completed", "failed"}
            for key in RETRYABLE_AGENTS
        )
    ):
        raise HTTPException(status_code=409, detail="Analysis fragments are not ready for synthesis")

    mark_agent_status(session, agent_key, "running")
    session.status = "running"
    session.error = None
    session.end_time = None


@app.post("/api/analysis/{analysis_id}/retry/{agent_key}", status_code=202, response_model=AnalysisRetry,
          responses={**TASK_ERRORS, **ADMISSION_ERRORS, 422: {"model": ApiError}})
async def retry_failed_agent(
    analysis_id: str, agent_key: str, principal: Annotated[ActiveSession, Depends(require_session_write)],
    store: TaskStorage,
):
    """Reserve capacity and retry a failed dimension using its original model settings."""
    def prepare(data):
        session = AnalysisStatus.model_validate(data)
        prepare_analysis_retry(session, agent_key)
        return session, task_snapshot(session)

    async def admit():
        if store is None:
            session = await require_owned_analysis(analysis_id, principal, store)
            prepare_analysis_retry(session, agent_key)
        else:
            session, settings = await task_db_call(store.retry, principal.user_id, analysis_id, prepare)
            session._store = store
            secret, url, model, session._summary_mode = settings
            session._api_settings = ApiSettings(secret, url, model)
        launch_job(session, retry_agent_and_summary, agent_key)

    if store is None:
        await admit()
    else:
        await complete_admission(admit())
    return {"analysis_id": analysis_id, "agent": agent_key, "status": "retrying"}

@app.get("/api/result/{analysis_id}", response_model=AnalysisReport | None, response_model_exclude_unset=True,
         responses={**TASK_ERRORS, 400: {"model": ApiError}})
async def get_analysis_result(session: AnalysisStatus = Depends(require_owned_analysis)):
    """Get the full result of a completed analysis"""

    if session.status not in {"completed", "degraded"}:
        raise HTTPException(status_code=400, detail=f"Analysis not completed. Current status: {session.status}")

    return session.result

@app.get("/api/report-pdf/{analysis_id}", response_class=FileResponse, responses={
    **TASK_ERRORS,
    200: {"content": {"application/pdf": {"schema": {"type": "string", "format": "binary"}}}},
    206: {"content": {"application/pdf": {"schema": {"type": "string", "format": "binary"}}}},
    400: {"model": ApiError}, 404: {"model": PdfError}, 500: {"model": PdfError},
})
async def download_report_pdf(session: AnalysisStatus = Depends(require_owned_analysis)):
    """Download the PDF report for a completed analysis.

    Only complete PDFs are published. Distinguish a failed build from a pending
    background job so the frontend can stop polling on missing tools or TeX errors.
    """

    if session.status not in {"completed", "degraded"}:
        raise HTTPException(status_code=400, detail=f"Analysis not completed. Current status: {session.status}")

    # Get report_path from result
    report_path = ""
    if session.result:
        report_path = session.result.get("report_path", "")

    if not report_path:
        raise HTTPException(status_code=404, detail={"status": "unavailable", "message": "No report file found"})

    # Derive PDF path from MD path (file-system-based approach)
    # reports/md/xxx.md -> reports/pdf/xxx.pdf (shared helper)
    pdf_path = derive_pdf_path(report_path)

    if not os.path.isfile(pdf_path) or not os.path.getsize(pdf_path):
        status = session.result.get("pdf_status") or get_pdf_status(report_path)["status"]
        if status == "failed":
            raise HTTPException(500, {"status": "failed", "message": "PDF 生成失败，请在本机检查 Pandoc 与 XeLaTeX/Tectonic 日志。"})
        if status == "pending":
            raise HTTPException(404, {"status": "pending", "message": "PDF 正在生成。"})
        if not os.path.isfile(pdf_path) or not os.path.getsize(pdf_path):
            raise HTTPException(404, {"status": "unavailable", "message": "PDF 文件不可用。"})

    # Generate a user-friendly filename
    company_name = (session.result and session.result.get("company_name", "")) or "report"
    stock_code = (session.result and session.result.get("stock_code", "")) or ""
    date_str = (session.result and session.result.get("analysis_date", "")) or ""
    profile_suffix = f"_{session.api_profile}" if session.api_profile else ""
    download_name = f"FINEX_{company_name}_{stock_code}_{date_str}{profile_suffix}.pdf"

    return FileResponse(
        path=pdf_path,
        media_type="application/pdf",
        filename=download_name
    )

@app.get("/api/history", response_model=AnalysisHistory, responses=STORAGE_ERRORS)
async def get_analysis_history(principal: Annotated[ActiveSession, Depends(require_session)], store: TaskStorage):
    """Get list of recent analyses (including running tasks)"""
    if store is not None:
        return {"history": await task_db_call(store.history, principal.user_id)}
    history = []
    owned = [session for session in analysis_sessions.values() if session.owner_id == principal.user_id]
    for session in owned[-10:]:
        entry = {
            "analysis_id": session.analysis_id,
            "company_name": (session.result and session.result.get("company_name")) or session.company_name or session.query or "Unknown",
            "stock_code": (session.result and session.result.get("stock_code")) or "",
            "analysis_date": (session.result and session.result.get("analysis_date")) or session.start_time or "",
            "status": session.status,
            "api_profile": session.api_profile,
        }
        history.append(entry)

    return {"history": history}

LOCAL_DELETE = [Depends(require_local_history_access)]


def require_idle_report_files(directory: Path):
    if any(is_pdf_generation_running(str(path)) for path in (directory / "md").glob("*.md")):
        raise HTTPException(409, "PDF 正在生成中，请完成后再删除研报")


def delete_task_directory(directory: Path):
    try:
        if directory.exists():
            shutil.rmtree(directory)
    except OSError as exc:
        raise HTTPException(500, "任务已从历史移除，文件清理未完成。可重试删除或重启服务。") from exc


@app.delete("/api/history/{analysis_id}", dependencies=LOCAL_DELETE, response_model=AnalysisDeleted,
            responses={**TASK_ERRORS, 409: {"model": ApiError}})
@app.delete("/api/analysis/{analysis_id}", dependencies=LOCAL_DELETE, response_model=AnalysisDeleted,
            responses={**TASK_ERRORS, 409: {"model": ApiError}})
async def delete_analysis_history(
    analysis_id: str, principal: Annotated[ActiveSession, Depends(require_session_write)], store: TaskStorage,
):
    """Commit the authorized deletion before removing private report files."""
    if store is not None:
        await task_db_call(store.delete, principal.user_id, analysis_id, require_idle_report_files, delete_task_directory)
    else:
        delete_memory_analysis(await require_owned_analysis(analysis_id, principal, store))
    return {"status": "deleted", "analysis_id": analysis_id, "message": "研报已成功删除"}


def delete_memory_analysis(session: AnalysisStatus):
    if session.status in {"running", "pending"}:
        raise HTTPException(status_code=409, detail="分析任务正在进行中，无法删除")

    # Clean up generated markdown and PDF files if they exist
    report_path = (session.result and session.result.get("report_path")) or ""
    pdf_path = (session.result and session.result.get("pdf_path")) or (derive_pdf_path(report_path) if report_path else "")

    if report_path and is_pdf_generation_running(report_path):
        raise HTTPException(status_code=409, detail="PDF 正在生成中，请完成后再删除研报")

    # Preserve the session until every file has been removed. A retry may safely
    # skip files already removed by a partially successful previous attempt.
    paths = []
    if pdf_path:
        pdf_path_obj = Path(pdf_path)
        paths.extend((pdf_path_obj, pdf_path_obj.with_suffix(".pdf.status.json"),
                      pdf_path_obj.with_suffix(".pdf.log")))
    if report_path:
        paths.append(Path(report_path))
    try:
        for path in paths:
            path.unlink(missing_ok=True)
    except OSError:
        raise HTTPException(status_code=500, detail="研报文件清理失败，历史记录已保留，请稍后重试")

    del analysis_sessions[session.analysis_id]

ProfileId = Literal["A", "B", "C", "D", "E"]
PROFILE_IDS = ("A", "B", "C", "D", "E")
CONFIG_FIELDS = ApiSettings._fields


def active_profile() -> ProfileId:
    profile = os.getenv(PROFILE_ENV_KEY, "A")
    return profile if profile in PROFILE_IDS else "A"


def profile_env_values(profile: ProfileId, settings: ApiSettings) -> dict[str, str]:
    return {f"FINEX_API_{profile}_{field.upper()}": value
            for field, value in zip(CONFIG_FIELDS, settings)}


def read_profiles() -> dict[ProfileId, ApiSettings]:
    active = active_profile()
    stored = dotenv_values(env_path, interpolate=False)
    return {
        profile: current_api_settings() if profile == active else ApiSettings(*(
            stored.get(f"FINEX_API_{profile}_{field.upper()}") or "" for field in CONFIG_FIELDS
        ))
        for profile in PROFILE_IDS
    }


def config_view(settings: ApiSettings) -> dict[str, str]:
    return {**settings._asdict(), "api_key": mask_api_key(settings.api_key)}


def profiles_view(profiles: dict[ProfileId, ApiSettings]) -> dict:
    return {
        "active_profile": active_profile(),
        "profiles": {
            profile: {"has_api_key": bool(settings.api_key), "masked_api_key": mask_api_key(settings.api_key), "base_url": settings.base_url, "model": settings.model}
            for profile, settings in profiles.items()
        },
    }


def merge_api_config(config: ApiConfigRequest, saved: ApiSettings) -> ApiSettings:
    updates = config.model_dump(exclude_none=True)
    if any(char in value for value in updates.values() for char in "\r\n\0"):
        raise HTTPException(status_code=422, detail="API 配置必须是单行文本")
    validate_config_destination(config, saved)
    return saved._replace(**updates)


def persist_profiles(profiles: dict[ProfileId, ApiSettings], active: ProfileId) -> None:
    updates = {PROFILE_ENV_KEY: active, **dict(zip(API_ENV_KEYS, profiles[active]))}
    for profile, settings in profiles.items():
        updates.update(profile_env_values(profile, settings))
    try:
        update_env_file(env_path, updates)
    except OSError:
        raise HTTPException(status_code=500, detail="无法保存本地 API 配置") from None
    os.environ.update({key: updates[key] for key in (*API_ENV_KEYS, PROFILE_ENV_KEY)})


@app.get("/api/config", dependencies=[Depends(require_local_config_access)])
async def get_api_config():
    """Return the active configuration for existing clients."""
    return config_view(current_api_settings())


@app.post("/api/config", dependencies=[Depends(require_local_config_access)])
async def update_api_config(config: ApiConfigRequest):
    if not config.model_dump(exclude_none=True):
        raise HTTPException(status_code=400, detail="未提供任何要更新的配置项")
    active = active_profile()
    profiles = read_profiles()
    profiles[active] = merge_api_config(config, profiles[active])
    persist_profiles(profiles, active)
    return {"status": "ok", "message": "配置已更新", **config_view(profiles[active])}


@app.get("/api/config/profiles", dependencies=[Depends(require_local_config_access)])
async def get_api_profiles():
    return profiles_view(read_profiles())


@app.put("/api/config/profiles/{profile}", dependencies=[Depends(require_local_config_access)])
async def save_api_profile(profile: ProfileId, config: ApiConfigRequest, activate: bool = False):
    active = profile if activate else active_profile()
    profiles = read_profiles()
    profiles[profile] = merge_api_config(config, profiles[profile])
    if profile == active and not all(profiles[profile]):
        raise HTTPException(status_code=422, detail="启用的配置需要完整的 API Key、Base URL 和 Model")
    persist_profiles(profiles, active)
    return profiles_view(profiles)


@app.post("/api/config/test", dependencies=[Depends(require_local_config_access)])
async def test_api_config_connectivity(config: Optional[ApiConfigRequest] = None):
    return await test_api_settings(merge_api_config(config or ApiConfigRequest(), current_api_settings()))


@app.post("/api/config/profiles/{profile}/test", dependencies=[Depends(require_local_config_access)])
async def test_api_profile(profile: ProfileId, config: Optional[ApiConfigRequest] = None):
    return await test_api_settings(merge_api_config(config or ApiConfigRequest(), read_profiles()[profile]))


async def test_api_settings(settings: ApiSettings):
    api_key, base_url, model_name = settings
    checks = {"chat": {"status": "skipped", "message": "未执行"}, "tools": {"status": "skipped", "message": "未执行"}}
    if not all([api_key, base_url, model_name]):
        return {
            "ok": False,
            "error": "配置不完整:缺少 API Key / Base URL / Model 之一,请先保存完整配置",
            "checks": checks,
        }

    try:
        llm = ChatOpenAI(
            model=model_name,
            api_key=api_key,
            base_url=base_url,
            temperature=0,
            max_tokens=128,
            timeout=20,
            max_retries=0,
        )
        # 发一个最小请求验证连通性
        resp = await llm.ainvoke([HumanMessage(content="ping")])
        reply = str(getattr(resp, "content", "") or resp)
        checks["chat"] = {"status": "passed", "message": f"对话接口可用（回复: {reply.replace(api_key, '***')[:50]}）"}
    except Exception as e:
        error = f"对话接口失败: {str(e).replace(api_key, '***')}"
        checks["chat"] = {"status": "failed", "message": error}
        checks["tools"]["message"] = "对话接口未通过，未检查工具调用"
        return {"ok": False, "error": error, "checks": checks}

    try:
        probe = {"type": "function", "function": {"name": "finex_connectivity_probe", "description": "验证工具调用", "parameters": {"type": "object", "properties": {"value": {"type": "string"}}, "required": ["value"]}}}
        response = await llm.bind_tools([probe]).ainvoke([HumanMessage(content="请调用 finex_connectivity_probe 工具，参数 value 设为 ok。")])
        if not any(call.get("name") == "finex_connectivity_probe" and call.get("args", {}).get("value") == "ok" for call in response.tool_calls):
            raise ValueError("模型未返回有效的工具调用")
        checks["tools"] = {"status": "passed", "message": "工具调用可用"}
        return {"ok": True, "message": "对话接口和工具调用均可用", "checks": checks}
    except Exception as e:
        error = f"工具调用未通过: {str(e).replace(api_key, '***')}"
        checks["tools"] = {"status": "failed", "message": error}
        return {"ok": False, "error": error, "checks": checks}

@app.get("/api/health")
async def health_check():
    """Health check endpoint"""
    return {"status": "healthy", "service": "FINEX API"}

@app.get("/api/market-kline", response_model=IndexMarketResponse | MarketError, response_model_exclude_unset=True)
async def market_kline(days: int = 120):
    """返回上证指数（sh.000001）真实历史日 K 线数据。

    用 baostock 日终数据（最近 N 个交易日收盘），供前端 K 线图消费。
    包在 asyncio.to_thread + asyncio.wait_for 里，避免阻塞事件循环，
    且 baostock 网络无响应时能有限超时，不会无限挂起。
    返回格式与 lightweight-charts 的 candle/histogram 数据兼容：
    time 用 Unix 秒。
    """
    import time as _time

    def _fetch_kline() -> list:
        end_date = datetime.now().strftime("%Y-%m-%d")
        # 上证指数日K，回溯约 days*2 个自然日以覆盖足够交易日
        start_date = (datetime.now() - timedelta(days=days * 2)).strftime("%Y-%m-%d")
        rs = safe_query(
            lambda: bs.query_history_k_data_plus(
                "sh.000001",
                "date,open,high,low,close,volume,amount",
                start_date=start_date,
                end_date=end_date,
                frequency="d",
                adjustflag="3",  # 不复权（指数无需复权）
            )
        )
        if rs.error_code != "0":
            raise RuntimeError(f"baostock 查询失败: {rs.error_msg}")
        rows = []
        while rs.next():
            row = rs.get_row_data()
            d = dict(zip(rs.fields, row))
            # 过滤空行，转成秒级时间戳
            ts = _time.mktime(_time.strptime(d["date"], "%Y-%m-%d"))
            rows.append({
                "time": int(ts),
                "open": float(d["open"]),
                "high": float(d["high"]),
                "low": float(d["low"]),
                "close": float(d["close"]),
                "volume": float(d["volume"] or 0),
            })
        return rows

    try:
        data = await asyncio.wait_for(
            asyncio.to_thread(_fetch_kline),
            timeout=BAOSTOCK_TIMEOUT_SECONDS,
        )
        if not data:
            return {"ok": False, "error": "未获取到上证指数K线数据"}
        return {"ok": True, "data": data}
    except asyncio.TimeoutError:
        return {"ok": False, "error": "获取行情超时，请稍后重试"}
    except Exception as e:
        print(f"Warning: market_kline failed: {e}")
        return {"ok": False, "error": str(e)}


@app.get("/api/stock-market", response_model=StockMarketResponse | MarketError, response_model_exclude_unset=True)
async def stock_market(code: str, days: int = 120, frequency: str = "d"):
    """Return real, end-of-day K-line data for one A-share stock."""
    if days < 20 or days > 500:
        raise HTTPException(status_code=422, detail="days must be between 20 and 500")
    try:
        return await asyncio.wait_for(
            asyncio.to_thread(
                fetch_stock_market,
                code,
                days,
                frequency,
                safe_query,
                bs,
            ),
            timeout=BAOSTOCK_TIMEOUT_SECONDS,
        )
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    except asyncio.TimeoutError:
        return {"ok": False, "error": "获取个股行情超时，请稍后重试"}
    except Exception as exc:
        print(f"Warning: stock_market failed: {exc}")
        return {"ok": False, "error": str(exc)}

# ============================================================================
# Static files (for CSS, JS, assets)
# ============================================================================

frontend_dir = Path(__file__).parent.parent / "frontend"
react_dist_dir = frontend_dir / "dist"


def require_local_preview(request: Request) -> None:
    require_local_page_access(request, "React 预览仅允许通过本机访问")


@app.get("/react-preview/", include_in_schema=False)
@app.get("/react-preview/app/history", include_in_schema=False)
@app.get("/react-preview/app/analysis/{analysis_id}", include_in_schema=False)
@app.get("/react-preview/app/analysis/{analysis_id}/report", include_in_schema=False)
async def serve_react_preview(request: Request):
    require_local_preview(request)
    entry = react_dist_dir / "index.html"
    if not entry.is_file():
        raise HTTPException(status_code=404, detail="React preview has not been built")
    return FileResponse(entry, media_type="text/html", headers={"Cache-Control": "no-cache"})


@app.get("/react-preview/assets/{asset_name}", include_in_schema=False)
async def serve_react_preview_asset(request: Request, asset_name: str):
    require_local_preview(request)
    if not re.fullmatch(r"[A-Za-z0-9_.-]+-[A-Za-z0-9_-]{8,}\.[A-Za-z0-9.]+", asset_name):
        raise HTTPException(status_code=404, detail="React preview asset not found")
    asset = react_dist_dir / "assets" / asset_name
    if not asset.is_file():
        raise HTTPException(status_code=404, detail="React preview asset not found")
    return FileResponse(asset, headers={"Cache-Control": "public, max-age=31536000, immutable"})


class LegacyStaticFiles(StaticFiles):
    async def get_response(self, path, scope):
        if path not in {"index.html", "workbench.css", "workbench.js"} and Path(path).parts[:1] != ("assets",):
            raise HTTPException(status_code=404, detail="Not Found")
        return await super().get_response(path, scope)


if frontend_dir.exists():
    app.mount("/static", LegacyStaticFiles(directory=frontend_dir), name="static")

# ============================================================================
# Main Entry Point
# ============================================================================

if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="127.0.0.1", port=8100)
