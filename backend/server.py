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
from datetime import datetime, timedelta
from typing import Optional, Dict, Any
from pathlib import Path

# Add project root and Financial-MCP-Agent to path
project_root = Path(__file__).parent.parent
sys.path.insert(0, str(project_root))
sys.path.insert(0, str(project_root / "agents"))

import asyncio
from fastapi import FastAPI, HTTPException
from fastapi.staticfiles import StaticFiles
from fastapi.responses import HTMLResponse, FileResponse
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel, Field, field_validator
import baostock as bs

# Import agent system components
from dotenv import load_dotenv
# Load .env from agents folder
env_path = Path(__file__).parent.parent / "agents" / ".env"
load_dotenv(env_path, override=True)

# LangGraph imports
from src.utils.workflow_builder import build_workflow
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
from src.utils.baostock_helper import ensure_logged_in, safe_query

# Import shared PDF path derivation (P2-6: 消除三处重复的路径推断逻辑)
from src.utils.pdf_converter import derive_pdf_path

# Import shared stock info extractor (P2-3: 合并 main.py 与 server.py 两套 extract_stock_info)
from src.utils.stock_extractor import extract_stock_info, COMPANY_CODE_MAP
from backend.market_data import fetch_stock_market

# Import MCP cleanup function
from src.tools.mcp_client import close_mcp_client_sessions

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

app = FastAPI(
    title="FINEX API",
    description="Financial Analysis AI Agent System API",
    version="1.0.0"
)

# CORS: 前端用纯 fetch 无凭证（无 cookie/Authorization），allow_credentials
# 设为 False。allow_origins=["*"] + allow_credentials=True 违反 CORS 规范，
# 且 Starlette 会回显任意源+凭证头，放大安全面。
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=False,
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.on_event("shutdown")
async def _shutdown_cleanup_mcp():
    """应用关停时统一清理 MCP 客户端缓存状态。

    MCP 工具列表在进程级缓存、跨请求复用，只在应用关闭时清理一次。
    工具对象每次调用自行管理 stdio 子进程生命周期，无需逐请求清理。
    """
    try:
        await close_mcp_client_sessions()
    except Exception as e:
        print(f"Warning: MCP cleanup error on shutdown: {e}")

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

    if data.get(error_key):
        detail.update({
            "status": "failed",
            "error": str(data[error_key]),
            "summary": "",
            "result_available": False,
        })
        session.progress[agent_key] = "failed"
        return

    text = str(data.get(result_key, "") or "")
    if text:
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


class ApiConfigRequest(BaseModel):
    """Request model for API config endpoint (所有字段可选,未传则保留原值)"""
    api_key: Optional[str] = None
    base_url: Optional[str] = None
    model: Optional[str] = None


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
                    key = stripped.split("=", 1)[0].strip()
                    if key in updates:
                        out_lines.append(f"{key}={updates[key]}\n")
                        remaining.pop(key, None)
                        continue
                out_lines.append(line)

    # 文件里没有的 key,追加到末尾
    for key, value in remaining.items():
        out_lines.append(f"{key}={value}\n")

    with open(path, "w", encoding="utf-8") as f:
        f.writelines(out_lines)


# ============================================================================
# In-memory storage for analysis sessions
# ============================================================================

analysis_sessions: Dict[str, AnalysisStatus] = {}

# ============================================================================
# Helper Functions
# ============================================================================


def lookup_stock_code_by_name(company_name: str) -> tuple:
    """
    用 baostock 根据公司名称查找股票代码（在线查找，覆盖所有A股）。
    返回 (stock_code: str or None, stock_name: str or None)

    使用进程级单例登录 + 互斥锁，避免并发请求互相踢掉 baostock 全局 session。
    """
    try:
        ensure_logged_in()
        rs = safe_query(lambda: bs.query_stock_basic())
        if rs.error_code != '0':
            return None, None

        while rs.next():
            row = rs.get_row_data()
            code_full = row[rs.fields.index('code')]
            name = row[rs.fields.index('code_name')]
            if name == company_name:
                pure_code = code_full.split('.')[1] if '.' in code_full else code_full
                return pure_code, name

        return None, None
    except Exception as e:
        print(f"Warning: baostock name lookup failed: {e}")
        return None, None

def verify_stock_code_exists(stock_code: str) -> tuple:
    """
    用 baostock 验证股票代码是否真实存在。
    返回 (exists: bool, stock_name: str or None)

    使用进程级单例登录 + 互斥锁，避免并发请求互相踢掉 baostock 全局 session。
    """
    try:
        ensure_logged_in()
        rs = safe_query(lambda: bs.query_stock_basic(code=stock_code))
        if rs.error_code == '0' and rs.next():
            name = rs.get_row_data()[rs.fields.index('code_name')] if 'code_name' in rs.fields else None
            return True, name
        return False, None
    except Exception as e:
        print(f"Warning: baostock verify failed: {e}")
        # 验证失败时不阻断流程，让 agent 自行处理
        return True, None

async def run_analysis_workflow(analysis_id: str, query: str):
    """Run the full analysis workflow in background"""
    session = analysis_sessions[analysis_id]
    session.status = "running"
    session.start_time = datetime.now().isoformat()

    try:
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
            metadata={"analysis_id": analysis_id}
        )

        # Build workflow（共享工厂，与 main.py 共用同一拓扑）
        async def _progress_cb(agent_key, status):
            mark_agent_status(session, agent_key, status)

        async def _result_cb(agent_key, result):
            record_agent_result(session, agent_key, result)

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

        # Execute workflow
        # 加总超时兜底：即使某个环节（LLM 调用、MCP/baostock 工具、ReAct 死循环）
        # 意外挂起，也能强制工作流结束，session 一定进入终态，前端不会永久卡住。
        # 超时后抛 TimeoutError 由下方 except 捕获置为 error。
        final_state = await asyncio.wait_for(
            app_workflow.ainvoke(initial_state),
            timeout=WORKFLOW_TIMEOUT_SECONDS
        )

        # Update status
        has_failed_dimensions = any(
            session.agent_details[key]["status"] == "failed"
            for key in ("fundamental", "technical", "value", "news")
        )
        session.status = "degraded" if has_failed_dimensions else "completed"
        session.end_time = datetime.now().isoformat()
        session.current_task = None

        # Extract results
        if final_state and final_state.get("data"):
            data = final_state["data"]
            rebuild_session_result(session, data)

    except asyncio.TimeoutError:
        session.status = "error"
        session.error = f"分析超时（超过 {WORKFLOW_TIMEOUT_SECONDS:.0f} 秒），请稍后重试。"
        session.end_time = datetime.now().isoformat()

    except Exception as e:
        session.status = "error"
        session.error = str(e)
        session.end_time = datetime.now().isoformat()

    finally:
        # 不在请求级别清理 MCP 客户端缓存。
        # 原因：MCP 工具列表是进程级缓存（见 mcp_client.py 说明），工具对象
        # 每次被调用时都会自行启动独立 stdio 子进程并在调用后关闭，不持有
        # 长驻连接。因此请求级 close 既无隔离收益，又会清掉缓存导致下一个
        # 请求要重新加载工具列表（启动子进程 + 握手 + list_tools）。
        # MCP 客户端的统一清理放在 FastAPI shutdown 事件中执行。
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

@app.post("/api/analyze")
async def start_analysis(request: AnalyzeRequest):
    """Start a new analysis task"""
    import uuid

    analysis_id = str(uuid.uuid4())[:8]

    # Create session
    session = AnalysisStatus(
        analysis_id=analysis_id,
        status="pending",
        progress={
            "fundamental": "waiting",
            "technical": "waiting",
            "value": "waiting",
            "news": "waiting",
            "summary": "waiting"
        },
        query=request.query
    )

    analysis_sessions[analysis_id] = session

    # 用 asyncio.create_task 在事件循环上并发调度,而非 BackgroundTasks。
    # BackgroundTasks 会在响应发送后 await 该协程,期间阻塞事件循环,
    # 导致 /api/status 轮询请求无法被处理(服务器看起来"卡住")。
    # create_task 让工作流与请求处理并发执行,轮询能正常响应。
    asyncio.create_task(run_analysis_workflow(analysis_id, request.query))

    return {
        "analysis_id": analysis_id,
        "status": "started",
        "message": f"Analysis started for: {request.query}"
    }

@app.get("/api/status/{analysis_id}")
async def get_analysis_status(analysis_id: str):
    """Get the current status of an analysis"""
    if analysis_id not in analysis_sessions:
        raise HTTPException(status_code=404, detail="Analysis not found")

    session = analysis_sessions[analysis_id]
    return {
        "analysis_id": session.analysis_id,
        "status": session.status,
        "progress": session.progress,
        "start_time": session.start_time,
        "end_time": session.end_time,
        "error": session.error,
        "agent_details": session.agent_details,
        "current_task": session.current_task,
    }


@app.get("/api/analysis/{analysis_id}/partial")
async def get_partial_results(analysis_id: str):
    """Return analysis dimensions that have completed so far."""
    session = analysis_sessions.get(analysis_id)
    if session is None:
        raise HTTPException(status_code=404, detail="Analysis not found")
    return {"analysis_id": analysis_id, "results": session.partial_results}

@app.get("/api/result/{analysis_id}")
async def get_analysis_result(analysis_id: str):
    """Get the full result of a completed analysis"""
    if analysis_id not in analysis_sessions:
        raise HTTPException(status_code=404, detail="Analysis not found")

    session = analysis_sessions[analysis_id]

    if session.status not in {"completed", "degraded"}:
        raise HTTPException(status_code=400, detail=f"Analysis not completed. Current status: {session.status}")

    return session.result

@app.get("/api/report-pdf/{analysis_id}")
async def download_report_pdf(analysis_id: str):
    """Download the PDF report for a completed analysis.

    Uses file-system-based check: derives the expected PDF path from the MD path
    and checks os.path.exists(). Returns the file if ready, 404 if not yet generated.
    """
    if analysis_id not in analysis_sessions:
        raise HTTPException(status_code=404, detail="Analysis not found")

    session = analysis_sessions[analysis_id]

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

    if not os.path.exists(pdf_path):
        raise HTTPException(status_code=404, detail={"status": "pending", "message": "PDF is still being generated"})

    # Generate a user-friendly filename
    company_name = (session.result and session.result.get("company_name", "")) or "report"
    stock_code = (session.result and session.result.get("stock_code", "")) or ""
    date_str = (session.result and session.result.get("analysis_date", "")) or ""
    download_name = f"FINEX_{company_name}_{stock_code}_{date_str}.pdf"

    return FileResponse(
        path=pdf_path,
        media_type="application/pdf",
        filename=download_name
    )

@app.get("/api/history")
async def get_analysis_history():
    """Get list of recent analyses (including running tasks)"""
    history = []
    for analysis_id, session in list(analysis_sessions.items())[-10:]:  # Last 10
        entry = {
            "analysis_id": analysis_id,
            "company_name": (session.result and session.result.get("company_name")) or session.company_name or session.query or "Unknown",
            "stock_code": (session.result and session.result.get("stock_code")) or "",
            "analysis_date": (session.result and session.result.get("analysis_date")) or session.start_time or "",
            "status": session.status
        }
        history.append(entry)

    return {"history": history}

@app.get("/api/config")
async def get_api_config():
    """返回当前 API 配置(api_key 脱敏显示)。"""
    return {
        "api_key": mask_api_key(os.getenv("OPENAI_COMPATIBLE_API_KEY", "")),
        "base_url": os.getenv("OPENAI_COMPATIBLE_BASE_URL", ""),
        "model": os.getenv("OPENAI_COMPATIBLE_MODEL", ""),
    }

# /api/config 写入的环境变量名(只允许更新这三个)
_CONFIG_ENV_KEYS = (
    "OPENAI_COMPATIBLE_API_KEY",
    "OPENAI_COMPATIBLE_BASE_URL",
    "OPENAI_COMPATIBLE_MODEL",
)

@app.post("/api/config")
async def update_api_config(config: ApiConfigRequest):
    """更新 API 配置:同时写 os.environ(立即生效)和 .env(持久化)。

    未传的字段(None)保留原值,只更新显式传入的字段。
    """
    # 收集需要更新的项(非 None)
    updates = {}
    if config.api_key is not None:
        updates["OPENAI_COMPATIBLE_API_KEY"] = config.api_key
    if config.base_url is not None:
        updates["OPENAI_COMPATIBLE_BASE_URL"] = config.base_url
    if config.model is not None:
        updates["OPENAI_COMPATIBLE_MODEL"] = config.model

    if not updates:
        raise HTTPException(status_code=400, detail="未提供任何要更新的配置项")

    # 1. 写 os.environ -- 立即生效(agents 在 call-time 用 os.getenv 读取)
    for key, value in updates.items():
        os.environ[key] = value

    # 2. 写 .env 文件 -- 持久化(重启后 load_dotenv 能读到)
    try:
        update_env_file(env_path, updates)
    except Exception as e:
        # .env 写入失败不影响运行时生效,但要告知用户
        return {
            "status": "warning",
            "message": f"运行时已生效,但 .env 持久化失败: {e}",
            "api_key": mask_api_key(os.getenv("OPENAI_COMPATIBLE_API_KEY", "")),
            "base_url": os.getenv("OPENAI_COMPATIBLE_BASE_URL", ""),
            "model": os.getenv("OPENAI_COMPATIBLE_MODEL", ""),
        }

    return {
        "status": "ok",
        "message": "配置已更新",
        "api_key": mask_api_key(os.getenv("OPENAI_COMPATIBLE_API_KEY", "")),
        "base_url": os.getenv("OPENAI_COMPATIBLE_BASE_URL", ""),
        "model": os.getenv("OPENAI_COMPATIBLE_MODEL", ""),
    }

@app.post("/api/config/test")
async def test_api_config_connectivity(config: Optional[ApiConfigRequest] = None):
    """测试 API 配置的连通性。

    优先用请求体里传入的表单值（前端测试按钮会把当前输入的
    base_url/model 传过来，让反馈与用户正在填的值一致）；未传的字段
    回退到 os.environ（上次已保存的配置）。

    返回 {ok: bool, message|error: str}。
    """
    api_key = config.api_key if config and config.api_key else os.getenv("OPENAI_COMPATIBLE_API_KEY")
    base_url = config.base_url if config and config.base_url else os.getenv("OPENAI_COMPATIBLE_BASE_URL")
    model_name = config.model if config and config.model else os.getenv("OPENAI_COMPATIBLE_MODEL")

    if not all([api_key, base_url, model_name]):
        return {
            "ok": False,
            "error": "配置不完整:缺少 API Key / Base URL / Model 之一,请先保存完整配置",
        }

    try:
        llm = ChatOpenAI(
            model=model_name,
            api_key=api_key,
            base_url=base_url,
            temperature=0,
            max_tokens=10,
        )
        # 发一个最小请求验证连通性
        resp = await llm.ainvoke([HumanMessage(content="ping")])
        reply = getattr(resp, "content", "") or str(resp)
        return {
            "ok": True,
            "message": f"连通正常,模型 {model_name} 已响应(回复: {reply[:50]})",
        }
    except Exception as e:
        return {
            "ok": False,
            "error": f"连通失败: {e}",
        }

@app.get("/api/health")
async def health_check():
    """Health check endpoint"""
    return {"status": "healthy", "service": "FINEX API"}

@app.get("/api/market-kline")
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
        ensure_logged_in()
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


@app.get("/api/stock-market")
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
                ensure_logged_in,
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
if frontend_dir.exists():
    app.mount("/static", StaticFiles(directory=str(frontend_dir)), name="static")

# ============================================================================
# Main Entry Point
# ============================================================================

if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8100)
