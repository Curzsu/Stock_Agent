"""
Agent Orchestration Layer - Async wrapper for multi-agent workflow execution
"""
import os
import sys
import re
import asyncio
from datetime import datetime
from typing import Dict, Any, Optional, AsyncGenerator, Callable, Awaitable
from dataclasses import dataclass, field
from enum import Enum

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from langgraph.graph import StateGraph, END
from dotenv import load_dotenv

from src.utils.state_definition import AgentState
from src.utils.logging_config import setup_logger
from src.utils.execution_logger import initialize_execution_logger, finalize_execution_logger, get_execution_logger
from src.agents.summary_agent import summary_agent
from src.agents.value_agent import value_agent
from src.agents.technical_agent import technical_agent
from src.agents.fundamental_agent import fundamental_agent
from src.agents.news_agent import news_agent
from src.tools.mcp_client import get_mcp_tools

load_dotenv(override=True)
logger = setup_logger(__name__)


class AgentType(Enum):
    FUNDAMENTAL = "fundamental_analyst"
    TECHNICAL = "technical_analyst"
    VALUE = "value_analyst"
    NEWS = "news_analyst"
    SUMMARY = "summarizer"


@dataclass
class AgentProgress:
    agent_name: str
    status: str
    message: str
    timestamp: datetime = field(default_factory=datetime.now)
    error: Optional[str] = None


@dataclass
class WorkflowResult:
    success: bool
    final_report: Optional[str] = None
    report_path: Optional[str] = None
    stock_code: Optional[str] = None
    company_name: Optional[str] = None
    errors: list = field(default_factory=list)
    execution_time: float = 0.0
    agent_results: Dict[str, str] = field(default_factory=dict)
    charts: list = field(default_factory=list)
    summary_metrics: Dict[str, Any] = field(default_factory=dict)


class StockInfoExtractor:
    STOCK_CODE_PATTERN = r'\b(\d{5,6})\b'
    
    STOCK_NAME_MAP = {
        '贵州茅台': 'sh.600519',
        '茅台': 'sh.600519',
        '中国银行': 'sh.601988',
        '中行': 'sh.601988',
        '工商银行': 'sh.601398',
        '工行': 'sh.601398',
        '建设银行': 'sh.601939',
        '建行': 'sh.601939',
        '农业银行': 'sh.601288',
        '农行': 'sh.601288',
        '招商银行': 'sh.600036',
        '招行': 'sh.600036',
        '中国平安': 'sh.601318',
        '平安': 'sh.601318',
        '比亚迪': 'sz.002594',
        '宁德时代': 'sz.300750',
        '宁德时代': 'sz.300750',
        '五粮液': 'sz.000858',
        '泸州老窖': 'sz.000568',
        '美的集团': 'sz.000333',
        '格力电器': 'sz.000651',
        '小米集团': 'hk.01810',
        '腾讯控股': 'hk.00700',
        '阿里巴巴': 'hk.09988',
        '京东': 'hk.09618',
        '万科': 'sz.000002',
        '保利发展': 'sh.600048',
        '中信证券': 'sh.600030',
        '海通证券': 'sh.600837',
        '东方财富': 'sz.300059',
        '同花顺': 'sz.300033',
        '恒瑞医药': 'sh.600276',
        '药明康德': 'sh.603259',
        '片仔癀': 'sh.600436',
        '云南白药': 'sz.000538',
        '长江电力': 'sh.600900',
        '中国神华': 'sh.601088',
        '中国石油': 'sh.601857',
        '中国石化': 'sh.600028',
        '海螺水泥': 'sh.600585',
        '万华化学': 'sh.600309',
        '隆基绿能': 'sh.601012',
        '通威股份': 'sh.600438',
        '立讯精密': 'sz.002475',
        '歌尔股份': 'sz.002241',
        '中芯国际': 'sh.688981',
        '韦尔股份': 'sh.603501',
        '兆易创新': 'sh.603986',
        '北方华创': 'sz.002371',
        '中微公司': 'sh.688012',
        '嘉友国际': 'sh.603871',
        '青岛啤酒': 'sh.600600',
        '海信视像': 'sh.600060',
    }
    
    COMPLEX_PATTERNS = [
        (r'请帮我分析一下\s*([^（(]+?)\s*[（(](\d{5,6})[)）]', lambda m: (m.group(1).strip(), m.group(2))),
        (r'分析一下\s*([^（(]+?)\s*[（(](\d{5,6})[)）]', lambda m: (m.group(1).strip(), m.group(2))),
        (r'分析\s*([^（(]+?)\s*[（(](\d{5,6})[)）]', lambda m: (m.group(1).strip(), m.group(2))),
        (r'分析\s*[（(](\d{5,6})[)）]\s*([^）)]+)', lambda m: (m.group(2).strip(), m.group(1))),
        (r'帮我看看\s*[（(](\d{5,6})[)）]\s*([^）)]+?)(?:\s*这只|\s*这个)?\s*股票', lambda m: (m.group(2).strip(), m.group(1))),
        (r'我想了解一下\s*([^（(]+?)\s*[（(](\d{5,6})[)）]', lambda m: (m.group(1).strip(), m.group(2))),
        (r'帮我看看\s*([^（(]+?)\s*[（(](\d{5,6})[)）]', lambda m: (m.group(1).strip(), m.group(2))),
        (r'^([^（(]+?)\s*[（(](\d{5,6})[)）]', lambda m: (m.group(1).strip(), m.group(2))),
    ]
    
    NAME_PATTERNS = [
        r'分析一下\s*([^0-9（）()\s]+?)(?:\s*的|\s|$)',
        r'分析\s*([^0-9（）()\s]+)',
        r'([^0-9（）()\s]+)\s*(?:这只|这个|的)?\s*股票',
        r'了解一下\s*([^0-9（）()\s]+?)(?:\s*的|\s|$)',
        r'给我分析一下\s*([^0-9（）()\s]+?)(?:\s*的|\s|$)',
        r'([^0-9（）()\s]+?)\s*的\s*(?:财务表现 | 盈利能力 | 现金流状况 | 资产负债情况 | 技术面 | 股价走势 | 技术指标 | 技术面表现 | 估值水平 | 市盈率 | 市净率 | 估值 | 投资风险 | 风险因素 | 风险评估 | 投资价值 | 股票 | 基本面情况 | 基本面 | 财务状况)',
        r'([^0-9（）()\s]+?)\s*在\s*[^0-9（）()\s]*\s*中',
        r'([^0-9（）()\s]+?)\s*面临',
    ]
    
    STOP_WORDS = ['的', '这个', '这只', '一下', '看看', '了解', '分析', '帮我', '我想', '给我', 
                 '财务状况', '投资价值', '基本面情况', '这只股票', '这个股票']

    @classmethod
    def extract(cls, query: str) -> tuple[Optional[str], Optional[str]]:
        company_name, stock_code = cls._try_complex_patterns(query)
        
        if not stock_code:
            stock_code = cls._extract_stock_code(query)
        
        if not company_name:
            company_name = cls._extract_company_name(query)
        
        if company_name:
            company_name = cls._clean_company_name(company_name)
            if not stock_code:
                stock_code = cls._lookup_stock_code(company_name)
        
        return company_name, stock_code

    @classmethod
    def _lookup_stock_code(cls, company_name: str) -> Optional[str]:
        """从股票名称映射表中查找股票代码"""
        if not company_name:
            return None
        
        for name, code in cls.STOCK_NAME_MAP.items():
            if name in company_name or company_name in name:
                logger.info(f"Stock name lookup: '{company_name}' -> {code}")
                return code
        
        return None

    @classmethod
    def _try_complex_patterns(cls, query: str) -> tuple[Optional[str], Optional[str]]:
        for pattern, extractor in cls.COMPLEX_PATTERNS:
            match = re.search(pattern, query)
            if match:
                return extractor(match)
        return None, None

    @classmethod
    def _extract_stock_code(cls, query: str) -> Optional[str]:
        match = re.search(cls.STOCK_CODE_PATTERN, query)
        return match.group(1) if match else None

    @classmethod
    def _extract_company_name(cls, query: str) -> Optional[str]:
        for pattern in cls.NAME_PATTERNS:
            match = re.search(pattern, query)
            if match:
                name = match.group(1).strip()
                if len(name) >= 2:
                    return name
        return None

    @classmethod
    def _clean_company_name(cls, name: str) -> str:
        for word in cls.STOP_WORDS:
            name = name.replace(word, '')
        return name.strip() if len(name.strip()) >= 2 else None


class AgentOrchestrator:
    def __init__(self):
        self._workflow: Optional[StateGraph] = None
        self._compiled_app = None
        self._progress_callback: Optional[Callable[[AgentProgress], Awaitable[None]]] = None
        self._execution_logger = None
        self._current_progress: Dict[str, AgentProgress] = {}

    async def initialize(self) -> None:
        self._workflow = StateGraph(AgentState)
        self._workflow.add_node("start_node", lambda state: state)
        self._workflow.add_node("fundamental_analyst", self._wrap_agent(fundamental_agent, AgentType.FUNDAMENTAL))
        self._workflow.add_node("technical_analyst", self._wrap_agent(technical_agent, AgentType.TECHNICAL))
        self._workflow.add_node("value_analyst", self._wrap_agent(value_agent, AgentType.VALUE))
        self._workflow.add_node("news_analyst", self._wrap_agent(news_agent, AgentType.NEWS))
        self._workflow.add_node("summarizer", self._wrap_agent(summary_agent, AgentType.SUMMARY))
        
        self._workflow.set_entry_point("start_node")
        
        for agent in [AgentType.FUNDAMENTAL, AgentType.TECHNICAL, AgentType.VALUE, AgentType.NEWS]:
            self._workflow.add_edge("start_node", agent.value)
            self._workflow.add_edge(agent.value, "summarizer")
        
        self._workflow.add_edge("summarizer", END)
        self._compiled_app = self._workflow.compile()

    def set_progress_callback(self, callback: Callable[[AgentProgress], Awaitable[None]]) -> None:
        self._progress_callback = callback

    async def _emit_progress(self, progress: AgentProgress) -> None:
        self._current_progress[progress.agent_name] = progress
        if self._progress_callback:
            await self._progress_callback(progress)

    def _wrap_agent(self, agent_func, agent_type: AgentType):
        async def wrapped(state: AgentState) -> Dict[str, Any]:
            agent_name = agent_type.value
            try:
                await self._emit_progress(AgentProgress(
                    agent_name=agent_name,
                    status="running",
                    message=self._get_agent_start_message(agent_type)
                ))
                
                result = await agent_func(state)
                
                await self._emit_progress(AgentProgress(
                    agent_name=agent_name,
                    status="completed",
                    message=self._get_agent_complete_message(agent_type)
                ))
                
                return result
            except Exception as e:
                await self._emit_progress(AgentProgress(
                    agent_name=agent_name,
                    status="error",
                    message=f"执行失败: {str(e)}",
                    error=str(e)
                ))
                raise
        
        return wrapped

    def _get_agent_start_message(self, agent_type: AgentType) -> str:
        messages = {
            AgentType.FUNDAMENTAL: "正在获取财务数据并进行基本面分析...",
            AgentType.TECHNICAL: "正在获取K线数据并进行技术面分析...",
            AgentType.VALUE: "正在获取估值数据并进行估值分析...",
            AgentType.NEWS: "正在爬取新闻并进行情感分析...",
            AgentType.SUMMARY: "正在整合各维度分析结果，生成综合研报...",
        }
        return messages.get(agent_type, f"正在执行{agent_type.value}...")

    def _get_agent_complete_message(self, agent_type: AgentType) -> str:
        messages = {
            AgentType.FUNDAMENTAL: "基本面分析完成",
            AgentType.TECHNICAL: "技术面分析完成",
            AgentType.VALUE: "估值分析完成",
            AgentType.NEWS: "新闻分析完成",
            AgentType.SUMMARY: "综合研报生成完成",
        }
        return messages.get(agent_type, f"{agent_type.value}完成")

    async def run_analysis(
        self, 
        user_query: str,
        progress_callback: Optional[Callable[[AgentProgress], Awaitable[None]]] = None
    ) -> WorkflowResult:
        if not self._compiled_app:
            await self.initialize()
        
        if progress_callback:
            self.set_progress_callback(progress_callback)
        
        self._execution_logger = initialize_execution_logger()
        start_time = datetime.now()
        
        company_name, stock_code = StockInfoExtractor.extract(user_query)
        logger.info(f"Extracted - Company: {company_name}, Stock Code: {stock_code}")
        
        if stock_code:
            stock_code = self._normalize_stock_code(stock_code)
        
        if not company_name and not stock_code:
            cleaned_query = user_query
            for word in ['分析', '一下', '的', '股票', '帮我', '看看', '请', '我', '想', '了解', '这个', '这只']:
                cleaned_query = cleaned_query.replace(word, '')
            cleaned_query = cleaned_query.strip()
            if cleaned_query and len(cleaned_query) >= 2:
                company_name = cleaned_query
                logger.info(f"Using cleaned query as company name: {company_name}")

        # 尝试通过MCP工具补充搜索股票代码
        if not stock_code and company_name:
            await self._emit_progress(AgentProgress(
                agent_name="system",
                status="initializing",
                message=f"正在搜索 '{company_name}' 的股票代码..."
            ))
            try:
                found_code = await self._search_stock_code_via_tool(company_name)
                if found_code:
                    stock_code = found_code
                    logger.info(f"Found stock code via tool: {company_name} -> {stock_code}")
                    await self._emit_progress(AgentProgress(
                        agent_name="system",
                        status="initializing",
                        message=f"找到股票代码: {stock_code}"
                    ))
            except Exception as e:
                logger.error(f"Error searching stock code: {e}")
        
        await self._emit_progress(AgentProgress(
            agent_name="system",
            status="initializing",
            message=f"初始化分析任务: {company_name or stock_code or user_query}"
        ))
        
        current_datetime = datetime.now()
        current_date_en = current_datetime.strftime("%Y-%m-%d")
        current_date_cn = current_datetime.strftime("%Y年%m月%d日")
        weekday_names = ["星期一", "星期二", "星期三", "星期四", "星期五", "星期六", "星期日"]
        current_weekday_cn = weekday_names[current_datetime.weekday()]
        current_time = current_datetime.strftime("%H:%M:%S")
        current_time_info = f"{current_date_cn} ({current_date_en}) {current_weekday_cn} {current_time}"
        
        initial_data = {
            "query": user_query,
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
            initial_data["stock_code"] = stock_code
        
        initial_state = AgentState(
            messages=[],
            data=initial_data,
            metadata={}
        )
        
        try:
            self._execution_logger.log_agent_start("main", {"user_query": user_query})
            
            final_state = await self._compiled_app.ainvoke(initial_state)
            
            execution_time = (datetime.now() - start_time).total_seconds()
            
            result = self._extract_result(final_state, execution_time)
            result.stock_code = stock_code
            result.company_name = company_name
            
            finalize_execution_logger(success=True)
            
            return result
            
        except Exception as e:
            logger.error(f"Workflow execution failed: {e}", exc_info=True)
            finalize_execution_logger(success=False, error=str(e))
            
            return WorkflowResult(
                success=False,
                errors=[str(e)],
                execution_time=(datetime.now() - start_time).total_seconds(),
                stock_code=stock_code,
                company_name=company_name
            )

    async def _search_stock_code_via_tool(self, company_name: str) -> Optional[str]:
        """使用 search_stock_by_name 工具搜索股票代码"""
        if not company_name:
            return None
            
        try:
            tools = await get_mcp_tools()
            search_tool = next((t for t in tools if t.name == "search_stock_by_name"), None)
            
            if not search_tool:
                logger.warning("Search tool not available")
                return None
                
            # 调用工具
            logger.info(f"Invoking search_stock_by_name for {company_name}")
            result = await search_tool.ainvoke({"name": company_name})
            
            # 简单的解析逻辑：查找 Markdown 表格中的第一行有效数据
            lines = result.strip().split('\n')
            for line in lines:
                # 跳过表头和分隔线
                if "code" in line.lower() or "---" in line or not "|" in line:
                    continue
                
                parts = [p.strip() for p in line.split('|')]
                # parts[0] is usually empty, parts[1] is code, parts[2] is tradeStatus, parts[3] is name
                # format: | code | tradeStatus | code_name |
                # The search_stock_by_name returns DataFrame with columns: code, tradeStatus, code_name
                # Markdown format:
                # | code | tradeStatus | code_name |
                # | sh.600600 | 1 | 青岛啤酒 |
                
                # parts[0] = ""
                # parts[1] = "sh.600600"
                # parts[2] = "1"
                # parts[3] = "青岛啤酒"
                
                if len(parts) >= 4:
                    code = parts[1]
                    name = parts[3]
                    # 验证是否包含公司名
                    if company_name in name or name in company_name:
                        return self._normalize_stock_code(code)
            
            return None
            
        except Exception as e:
            logger.error(f"Failed to search stock code via tool: {e}", exc_info=True)
            return None

    def _normalize_stock_code(self, code: str) -> str:
        if not code:
            return code
        
        code = code.strip()
        
        if code.startswith(('sh.', 'sz.', 'SH.', 'SZ.')):
            return code.lower()
        
        if len(code) == 6 and code.isdigit():
            if code.startswith('6'):
                return f"sh.{code}"
            elif code.startswith(('0', '3')):
                return f"sz.{code}"
        
        return code

    def _extract_result(self, final_state: AgentState, execution_time: float) -> WorkflowResult:
        if not final_state or not final_state.get("data"):
            return WorkflowResult(
                success=False,
                errors=["工作流返回无效状态"],
                execution_time=execution_time
            )
        
        data = final_state["data"]
        errors = []
        
        for key in ["fundamental_analysis_error", "technical_analysis_error", 
                     "value_analysis_error", "news_analysis_error", "summary_error"]:
            if key in data:
                errors.append(data[key])
        
        agent_results = {
            "fundamental_analysis": data.get("fundamental_analysis", ""),
            "technical_analysis": data.get("technical_analysis", ""),
            "value_analysis": data.get("value_analysis", ""),
            "news_analysis": data.get("news_analysis", ""),
        }
        
        return WorkflowResult(
            success="final_report" in data,
            final_report=data.get("final_report"),
            report_path=data.get("report_path"),
            errors=errors if errors else None,
            execution_time=execution_time,
            agent_results=agent_results,
            charts=data.get("charts", []),
            summary_metrics=data.get("summary_metrics", {})
        )

    def get_current_progress(self) -> Dict[str, AgentProgress]:
        return self._current_progress.copy()


_orchestrator_instance: Optional[AgentOrchestrator] = None


async def get_orchestrator() -> AgentOrchestrator:
    global _orchestrator_instance
    if _orchestrator_instance is None:
        _orchestrator_instance = AgentOrchestrator()
        await _orchestrator_instance.initialize()
    return _orchestrator_instance