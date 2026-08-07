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
from datetime import datetime
from typing import Optional, Dict, Any
from pathlib import Path

# Add project root and Financial-MCP-Agent to path
project_root = Path(__file__).parent.parent
sys.path.insert(0, str(project_root))
sys.path.insert(0, str(project_root / "agents"))

from fastapi import FastAPI, HTTPException, BackgroundTasks
from fastapi.staticfiles import StaticFiles
from fastapi.responses import HTMLResponse, FileResponse
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel, field_validator
import baostock as bs

# Import agent system components
from dotenv import load_dotenv
# Load .env from agents folder
env_path = Path(__file__).parent.parent / "agents" / ".env"
load_dotenv(env_path, override=True)

# LangGraph imports
from src.utils.workflow_builder import build_workflow

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

# Import MCP cleanup function
from src.tools.mcp_client import close_mcp_client_sessions

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
            stock_code, real_name = lookup_stock_code_by_name(company_name)
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
        exists, real_name = verify_stock_code_exists(full_code)
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

        initial_state = AgentState(
            messages=[],
            data=initial_data,
            metadata={"analysis_id": analysis_id}
        )

        # Build workflow（共享工厂，与 main.py 共用同一拓扑）
        async def _progress_cb(agent_key, status):
            session.progress[agent_key] = status

        app_workflow = build_workflow(
            fundamental_agent=fundamental_agent,
            technical_agent=technical_agent,
            value_agent=value_agent,
            news_agent=news_agent,
            summary_agent=summary_agent,
            progress_callback=_progress_cb,
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
        final_state = await app_workflow.ainvoke(initial_state)

        # Update status
        session.status = "completed"
        session.end_time = datetime.now().isoformat()

        # Extract results
        if final_state and final_state.get("data"):
            data = final_state["data"]
            report_path = data.get("report_path", "")
            pdf_path = data.get("pdf_path")  # May be None if background task not finished

            # File-system-based PDF check: derive expected PDF path from MD path
            # reports/md/xxx.md -> reports/pdf/xxx.pdf (shared helper)
            pdf_available = False
            if report_path:
                expected_pdf_path = derive_pdf_path(report_path)
                pdf_available = os.path.exists(expected_pdf_path)
                if pdf_available and not pdf_path:
                    pdf_path = expected_pdf_path

            session.result = {
                "company_name": company_name,
                "stock_code": stock_code,
                "query": query,
                "fundamental_analysis": data.get("fundamental_analysis", ""),
                "technical_analysis": data.get("technical_analysis", ""),
                "value_analysis": data.get("value_analysis", ""),
                "news_analysis": data.get("news_analysis", ""),
                "final_report": data.get("final_report", ""),
                "analysis_date": current_date_en,
                "report_path": report_path,
                "pdf_path": pdf_path or "",
                "pdf_available": pdf_available
            }

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
async def start_analysis(request: AnalyzeRequest, background_tasks: BackgroundTasks):
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

    # Run analysis in background
    background_tasks.add_task(run_analysis_workflow, analysis_id, request.query)

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
        "error": session.error
    }

@app.get("/api/result/{analysis_id}")
async def get_analysis_result(analysis_id: str):
    """Get the full result of a completed analysis"""
    if analysis_id not in analysis_sessions:
        raise HTTPException(status_code=404, detail="Analysis not found")

    session = analysis_sessions[analysis_id]

    if session.status != "completed":
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

    if session.status != "completed":
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

@app.get("/api/health")
async def health_check():
    """Health check endpoint"""
    return {"status": "healthy", "service": "FINEX API"}

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