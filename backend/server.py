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
import asyncio
import json
import re
from datetime import datetime
from typing import Optional, Dict, Any, List
from pathlib import Path

# Add project root and Financial-MCP-Agent to path
project_root = Path(__file__).parent.parent
sys.path.insert(0, str(project_root))
sys.path.insert(0, str(project_root / "agents"))

from fastapi import FastAPI, HTTPException, BackgroundTasks
from fastapi.staticfiles import StaticFiles
from fastapi.responses import HTMLResponse, JSONResponse
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel

# Import agent system components
from dotenv import load_dotenv
# Load .env from agents folder
env_path = Path(__file__).parent.parent / "agents" / ".env"
load_dotenv(env_path, override=True)

# LangGraph imports
from langgraph.graph import StateGraph, END

# Import agents (using src.* after adding agents to path)
from src.agents.fundamental_agent import fundamental_agent
from src.agents.technical_agent import technical_agent
from src.agents.value_agent import value_agent
from src.agents.news_agent import news_agent
from src.agents.summary_agent import summary_agent

# Import state definition
from src.utils.state_definition import AgentState

# ============================================================================
# FastAPI Application Setup
# ============================================================================

app = FastAPI(
    title="FINEX API",
    description="Financial Analysis AI Agent System API",
    version="1.0.0"
)

# Enable CORS for frontend access
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# ============================================================================
# Data Models
# ============================================================================

class AnalyzeRequest(BaseModel):
    """Request model for analysis endpoint"""
    query: str

class AnalysisStatus(BaseModel):
    """Status model for tracking analysis progress"""
    analysis_id: str
    status: str  # 'pending', 'running', 'completed', 'error'
    progress: Dict[str, str]  # agent_name -> status
    start_time: Optional[str] = None
    end_time: Optional[str] = None
    result: Optional[Dict[str, Any]] = None
    error: Optional[str] = None

# ============================================================================
# In-memory storage for analysis sessions
# ============================================================================

analysis_sessions: Dict[str, AnalysisStatus] = {}

# ============================================================================
# Helper Functions
# ============================================================================

# 常见公司名称到股票代码的映射表
COMPANY_CODE_MAP = {
    # A股知名公司
    "比亚迪": "002594",
    "茅台": "600519",
    "贵州茅台": "600519",
    "宁德时代": "300750",
    "中国平安": "601318",
    "平安银行": "000001",
    "招商银行": "600036",
    "腾讯": "00700",
    "阿里巴巴": "09988",
    "美团": "03690",
    "京东": "09618",
    "小米": "01810",
    "百度": "09888",
    "网易": "09999",
    "拼多多": "PDD",
    "理想汽车": "02015",
    "蔚来": "NIO",
    "小鹏汽车": "09868",
    "长城汽车": "601633",
    "上汽集团": "600104",
    "广汽集团": "601238",
    "一汽解放": "000800",
    "长安汽车": "000625",
    "东风汽车": "600006",
    "比亚迪电子": "00285",
    "隆基绿能": "601012",
    "隆基股份": "601012",
    "通威股份": "600438",
    "阳光电源": "300274",
    "晶澳科技": "002459",
    "天合光能": "688599",
    "晶科能源": "688223",
    "中国中免": "601888",
    "免税": "601888",
    "海天味业": "603288",
    "海天": "603288",
    "金龙鱼": "300999",
    "伊利股份": "600887",
    "伊利": "600887",
    "蒙牛乳业": "02319",
    "蒙牛": "02319",
    "双汇发展": "000895",
    "双汇": "000895",
    "恒瑞医药": "600276",
    "恒瑞": "600276",
    "药明康德": "603259",
    "药明": "603259",
    "迈瑞医疗": "300760",
    "迈瑞": "300760",
    "片仔癀": "600436",
    "云南白药": "000538",
    "同仁堂": "600085",
    "爱尔眼科": "300015",
    "爱尔": "300015",
    "通策医疗": "600763",
    "智飞生物": "300122",
    "沃森生物": "300142",
    "康泰生物": "300601",
    "华兰生物": "002007",
    "万泰生物": "603392",
    "中芯国际": "688981",
    "中芯": "688981",
    "韦尔股份": "603501",
    "韦尔": "603501",
    "兆易创新": "603986",
    "兆易": "603986",
    "北方华创": "002371",
    "华创": "002371",
    "中微公司": "688012",
    "中微": "688012",
    "澜起科技": "688008",
    "澜起": "688008",
    "寒武纪": "688256",
    "海光信息": "688041",
    "海光": "688041",
    "龙芯中科": "688047",
    "龙芯": "688047",
    "中际旭创": "300308",
    "中际": "300308",
    "新易盛": "300502",
    "天孚通信": "300394",
    "天孚": "300394",
    "华工科技": "000988",
    "光迅科技": "002281",
    "光迅": "002281",
    "中兴通讯": "000063",
    "中兴": "000063",
    "烽火通信": "600498",
    "烽火": "600498",
    "紫光股份": "000938",
    "紫光": "000938",
    "浪潮信息": "000977",
    "浪潮": "000977",
    "中科曙光": "603019",
    "曙光": "603019",
    "科大讯飞": "002230",
    "讯飞": "002230",
    "大华股份": "002236",
    "大华": "002236",
    "海康威视": "002415",
    "海康": "002415",
    "汇川技术": "300124",
    "汇川": "300124",
    "汇川技术": "300124",
    "三一重工": "600031",
    "三一": "600031",
    "徐工机械": "000425",
    "徐工": "000425",
    "中联重科": "000157",
    "中联": "000157",
    "恒立液压": "601100",
    "恒立": "601100",
    "浙江鼎力": "603338",
    "鼎力": "603338",
    "中国建筑": "601668",
    "中国中铁": "601390",
    "中国铁建": "601186",
    "中国交建": "601800",
    "中国电建": "601669",
    "中国能建": "601868",
    "中国核建": "601611",
    "中国中冶": "601618",
    "中国化学": "601117",
    "中国石油": "601857",
    "中石油": "601857",
    "中国石化": "600028",
    "中石化": "600028",
    "中国海油": "600938",
    "中海油": "600938",
    "中国神华": "601088",
    "神华": "601088",
    "陕西煤业": "601225",
    "陕煤": "601225",
    "兖矿能源": "600188",
    "兖矿": "600188",
    "中煤能源": "601898",
    "中煤": "601898",
    "潞安环能": "601699",
    "潞安": "601699",
    "山西焦煤": "000983",
    "山西焦化": "600740",
    "美锦能源": "000723",
    "美锦": "000723",
    "宝钢股份": "600019",
    "宝钢": "600019",
    "河钢股份": "000709",
    "河钢": "000709",
    "鞍钢股份": "000898",
    "鞍钢": "000898",
    "马钢股份": "600808",
    "马钢": "600808",
    "首钢股份": "000959",
    "首钢": "000959",
    "太钢不锈": "000825",
    "太钢": "000825",
    "包钢股份": "600010",
    "包钢": "600010",
    "中国铝业": "601600",
    "中铝": "601600",
    "江西铜业": "600362",
    "江铜": "600362",
    "紫金矿业": "601899",
    "紫金": "601899",
    "洛阳钼业": "603993",
    "洛钼": "603993",
    "华友钴业": "603799",
    "华友": "603799",
    "赣锋锂业": "002460",
    "赣锋": "002460",
    "天齐锂业": "002466",
    "天齐": "002466",
    "盐湖股份": "000792",
    "盐湖": "000792",
    "北方稀土": "600111",
    "北方": "600111",
    "五矿稀土": "000831",
    "五矿": "000831",
    "盛和资源": "600392",
    "盛和": "600392",
    "广晟有色": "600259",
    "广晟": "600259",
    "厦门钨业": "600549",
    "厦门钨": "600549",
    "章源钨业": "002378",
    "章源": "002378",
    "中金黄金": "600489",
    "中金": "600489",
    "山东黄金": "600547",
    "山金": "600547",
    "赤峰黄金": "600988",
    "赤峰": "600988",
    "银泰黄金": "000975",
    "银泰": "000975",
    "湖南黄金": "002155",
    "湖南": "002155",
    "西部矿业": "601168",
    "西部": "601168",
    "云南铜业": "000878",
    "云铜": "000878",
    "铜陵有色": "000630",
    "铜陵": "000630",
}

def extract_stock_info(query: str) -> tuple:
    """Extract stock code and company name from user query"""
    stock_code = None
    company_name = None

    # Pattern 1: Company name with code in parentheses
    patterns = [
        (r'分析\s*([^（(]+?)\s*[（(](\d{5,6})[)）]', 1, 2),
        (r'([^（(]+?)\s*[（(](\d{5,6})[)）]', 1, 2),
        (r'(\d{5,6})', None, 1),  # Just stock code
        (r'分析\s*([^0-9（）()\s]+)', 1, None),  # Company name after "分析"
        (r'([^0-9（）()\s]+)\s*(?:这只|这个)?\s*股票', 1, None),  # Company before "股票"
        (r'^([^\d\s（）()]+)$', 1, None),  # Just company name (e.g., "比亚迪")
    ]

    for pattern, name_group, code_group in patterns:
        match = re.search(pattern, query)
        if match:
            if name_group:
                company_name = match.group(name_group).strip()
            if code_group:
                stock_code = match.group(code_group)
            if stock_code or company_name:
                break

    # Clean company name
    if company_name:
        stop_words = ['的', '这个', '这只', '一下', '看看', '了解', '分析', '帮我', '我想', '给我', '怎么样', '如何']
        for word in stop_words:
            company_name = company_name.replace(word, '').strip()
        if len(company_name) < 2:
            company_name = None

    # If we have company name but no stock code, look up in the mapping table
    if company_name and not stock_code:
        # Try exact match first
        if company_name in COMPANY_CODE_MAP:
            stock_code = COMPANY_CODE_MAP[company_name]
        else:
            # Try partial match (e.g., "比亚迪" matches keys containing "比亚迪")
            for name, code in COMPANY_CODE_MAP.items():
                if company_name in name or name in company_name:
                    stock_code = code
                    break

    return company_name, stock_code

async def run_analysis_workflow(analysis_id: str, query: str):
    """Run the full analysis workflow in background"""
    session = analysis_sessions[analysis_id]
    session.status = "running"
    session.start_time = datetime.now().isoformat()

    try:
        # Extract stock info
        company_name, stock_code = extract_stock_info(query)

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

        # Build workflow
        workflow = StateGraph(AgentState)

        # Add nodes with progress tracking
        async def fundamental_with_progress(state):
            result = await fundamental_agent(state)
            session.progress["fundamental"] = "completed"
            return result

        async def technical_with_progress(state):
            result = await technical_agent(state)
            session.progress["technical"] = "completed"
            return result

        async def value_with_progress(state):
            result = await value_agent(state)
            session.progress["value"] = "completed"
            return result

        async def news_with_progress(state):
            result = await news_agent(state)
            session.progress["news"] = "completed"
            return result

        async def summary_with_progress(state):
            session.progress["summary"] = "running"
            result = await summary_agent(state)
            session.progress["summary"] = "completed"
            return result

        workflow.add_node("start_node", lambda state: state)
        workflow.add_node("fundamental_analyst", fundamental_with_progress)
        workflow.add_node("technical_analyst", technical_with_progress)
        workflow.add_node("value_analyst", value_with_progress)
        workflow.add_node("news_analyst", news_with_progress)
        workflow.add_node("summarizer", summary_with_progress)

        # Set entry point
        workflow.set_entry_point("start_node")

        # Add edges for parallel execution
        workflow.add_edge("start_node", "fundamental_analyst")
        workflow.add_edge("start_node", "technical_analyst")
        workflow.add_edge("start_node", "value_analyst")
        workflow.add_edge("start_node", "news_analyst")

        # Converge to summarizer
        workflow.add_edge("fundamental_analyst", "summarizer")
        workflow.add_edge("technical_analyst", "summarizer")
        workflow.add_edge("value_analyst", "summarizer")
        workflow.add_edge("news_analyst", "summarizer")

        # End
        workflow.add_edge("summarizer", END)

        # Compile and run
        app_workflow = workflow.compile()

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
                "report_path": data.get("report_path", "")
            }

    except Exception as e:
        session.status = "error"
        session.error = str(e)
        session.end_time = datetime.now().isoformat()

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
        }
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

@app.get("/api/history")
async def get_analysis_history():
    """Get list of recent analyses"""
    history = []
    for analysis_id, session in list(analysis_sessions.items())[-10:]:  # Last 10
        if session.status == "completed" and session.result:
            history.append({
                "analysis_id": analysis_id,
                "company_name": session.result.get("company_name", "Unknown"),
                "stock_code": session.result.get("stock_code", ""),
                "analysis_date": session.result.get("analysis_date", ""),
                "status": session.status
            })

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
    uvicorn.run(app, host="0.0.0.0", port=8000)