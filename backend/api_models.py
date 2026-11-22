"""Public API contracts shared by the legacy and React workbenches."""

from typing import Literal

from pydantic import BaseModel, Field


TaskStatus = Literal["pending", "running", "completed", "degraded", "error"]
AgentStatus = Literal["waiting", "running", "completed", "failed"]
AgentName = Literal["fundamental", "technical", "value", "news", "summary"]


class ApiError(BaseModel):
    detail: str


class AnalysisCreated(BaseModel):
    analysis_id: str
    status: Literal["started"]
    message: str


class AgentDetail(BaseModel):
    status: AgentStatus
    started_at: str | None = None
    completed_at: str | None = None
    execution_time_ms: int | None = None
    summary: str = ""
    result_available: bool = False
    error: str | None = None


class AnalysisStatusResponse(BaseModel):
    analysis_id: str
    status: TaskStatus
    progress: dict[str, AgentStatus]
    agent_details: dict[str, AgentDetail]
    start_time: str | None
    end_time: str | None
    error: str | None
    current_task: str | None
    company_name: str | None
    stock_code: str | None


class AnalysisFragments(BaseModel):
    fundamental_analysis: str = ""
    technical_analysis: str = ""
    value_analysis: str = ""
    news_analysis: str = ""
    final_report: str = ""


class AnalysisPartial(BaseModel):
    analysis_id: str
    results: AnalysisFragments


class AnalysisRetry(BaseModel):
    analysis_id: str
    agent: AgentName
    status: Literal["retrying"]


class AnalysisReport(AnalysisFragments):
    company_name: str = ""
    stock_code: str = ""
    query: str = ""
    analysis_date: str = ""
    pdf_available: bool = False
    missing_dimensions: list[AgentName] = Field(default_factory=list)


class HistoryItem(BaseModel):
    analysis_id: str
    company_name: str
    stock_code: str
    analysis_date: str
    status: TaskStatus
    api_profile: str | None


class AnalysisHistory(BaseModel):
    history: list[HistoryItem]


class AnalysisDeleted(BaseModel):
    status: Literal["deleted"]
    analysis_id: str
    message: str


class PdfState(BaseModel):
    status: Literal["pending", "failed", "unavailable"]
    message: str


class PdfError(BaseModel):
    detail: str | PdfState


class CandleValues(BaseModel):
    open: float
    high: float
    low: float
    close: float
    volume: float


class IndexCandle(CandleValues):
    time: int


class StockCandle(CandleValues):
    time: str
    ma5: float | None
    ma20: float | None


class MarketQuote(BaseModel):
    open: float | None = None
    high: float | None = None
    low: float | None = None
    close: float
    volume: float | None = None
    turnover: float | None = None
    pct_change: float | None = None
    pe_ttm: float | None = None
    pb_mrq: float | None = None


class IndexMarketResponse(BaseModel):
    ok: Literal[True]
    data: list[IndexCandle]


class StockMarketResponse(BaseModel):
    ok: Literal[True]
    code: str
    latest_trade_date: str
    quote: MarketQuote
    candles: list[StockCandle]


class MarketError(BaseModel):
    ok: Literal[False]
    error: str
    code: str = ""
