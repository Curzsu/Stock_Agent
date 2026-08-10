# Stock Analysis Workbench Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Replace the separate analysis-progress and report pages with one responsive stock-research workbench that shows five live agent cards, real individual-stock market data, incremental agent results, degraded-state recovery, and the completed report in place.

**Architecture:** Keep FastAPI and the existing LangGraph fan-out/fan-in workflow, but add a result callback so completed agent output is persisted before the full workflow ends. Add a small market-data module and backward-compatible session fields/endpoints. Move the new browser logic and styling into focused static files while keeping the existing landing page and its current inline behavior intact.

**Tech Stack:** Python 3, FastAPI, Pydantic 2, LangGraph, BaoStock, unittest/TestClient, vanilla JavaScript, Node built-in test runner, Lightweight Charts, HTML/CSS.

---

## File Structure

- Create `backend/market_data.py`: normalize stock codes, query BaoStock, calculate MA5/MA20, and build the structured market payload.
- Create `frontend/workbench.js`: pure workbench state helpers plus the DOM controller exposed as `window.FinexWorkbench`.
- Create `frontend/workbench.css`: confirmed warm research-report visual system, 2 × 2 + 1 agent grid, market panel, report state, responsive rules, and reduced-motion rules.
- Create `tests/test_market_data.py`: unit tests for code normalization, moving averages, payload shape, and empty/invalid data.
- Create `tests/test_analysis_session_api.py`: TestClient and helper tests for status details, partial results, degraded sessions, and retry validation.
- Create `tests/frontend/test_workbench.cjs`: Node tests for phase derivation, safe status normalization, market-series conversion, and partial-result change detection.
- Modify `agents/src/utils/workflow_builder.py`: add an optional result callback without changing CLI behavior.
- Modify `tests/test_workflow_builder.py`: prove result callbacks receive each agent result and existing callbacks remain compatible.
- Modify `backend/server.py`: extend `AnalysisStatus`, persist incremental results, expose market/partial/retry APIs, and permit degraded reports.
- Modify `frontend/index.html`: replace the old analysis/report markup and wire the existing analysis lifecycle to the new controller.
- Modify `tests/test_end_to_end.py`: assert the near-real workflow still produces all result fields after callback changes.

## Execution Preflight

The current main checkout contains an uncommitted user change in `frontend/index.html`. Before Task 1, use `superpowers:using-git-worktrees` and ask for consent to create an isolated worktree. If approved, create branch `codex/stock-analysis-workbench`, then apply a patch containing only the current `frontend/index.html` diff to the worktree as the baseline. Do not commit that baseline separately or alter the original checkout. If worktree isolation is declined, execute in place and inspect every patch hunk against the existing frontend diff.

### Task 1: Add Incremental Result Callbacks to the Workflow

**Files:**
- Modify: `tests/test_workflow_builder.py`
- Modify: `agents/src/utils/workflow_builder.py`

- [ ] **Step 1: Write the failing result-callback test**

Add this test beside `test_progress_callback_invoked`:

```python
def test_result_callback_receives_each_agent_result(self):
    from src.utils.workflow_builder import build_workflow

    results = {}

    async def result_cb(agent_key, result):
        results[agent_key] = result["data"]

    app = build_workflow(
        fundamental_agent=_make_fake_agent("fundamental_analysis", "F"),
        technical_agent=_make_fake_agent("technical_analysis", "T"),
        value_agent=_make_fake_agent("value_analysis", "V"),
        news_agent=_make_fake_agent("news_analysis", "N"),
        summary_agent=_make_fake_agent("final_report", "R"),
        result_callback=result_cb,
    )

    asyncio.run(app.ainvoke(_make_initial_state()))

    self.assertEqual(results["fundamental"]["fundamental_analysis"], "F")
    self.assertEqual(results["technical"]["technical_analysis"], "T")
    self.assertEqual(results["value"]["value_analysis"], "V")
    self.assertEqual(results["news"]["news_analysis"], "N")
    self.assertEqual(results["summary"]["final_report"], "R")
```

- [ ] **Step 2: Run the focused test and verify RED**

Run:

```powershell
python -m unittest tests.test_workflow_builder.TestBuildWorkflow.test_result_callback_receives_each_agent_result -v
```

Expected: `TypeError: build_workflow() got an unexpected keyword argument 'result_callback'`.

- [ ] **Step 3: Add the optional result callback**

Update the factory signature and wrapper:

```python
from typing import Awaitable, Callable, Optional

def build_workflow(
    fundamental_agent: Callable,
    technical_agent: Callable,
    value_agent: Callable,
    news_agent: Callable,
    summary_agent: Callable,
    progress_callback: Optional[Callable[[str, str], Awaitable[None]]] = None,
    result_callback: Optional[Callable[[str, dict], Awaitable[None]]] = None,
):
    workflow.add_node(
        "fundamental_analyst",
        _wrap(fundamental_agent, "fundamental", progress_callback, result_callback),
    )
    workflow.add_node(
        "technical_analyst",
        _wrap(technical_agent, "technical", progress_callback, result_callback),
    )
    workflow.add_node(
        "value_analyst",
        _wrap(value_agent, "value", progress_callback, result_callback),
    )
    workflow.add_node(
        "news_analyst",
        _wrap(news_agent, "news", progress_callback, result_callback),
    )
    workflow.add_node(
        "summarizer",
        _wrap(summary_agent, "summary", progress_callback, result_callback),
    )

def _wrap(agent, agent_key, progress_callback, result_callback):
    if progress_callback is None and result_callback is None:
        return agent

    async def wrapped(state):
        if progress_callback is not None:
            await progress_callback(agent_key, "running")
        result = await agent(state)
        if result_callback is not None:
            await result_callback(agent_key, result)
        if progress_callback is not None:
            await progress_callback(agent_key, "completed")
        return result

    return wrapped
```

- [ ] **Step 4: Run workflow tests and verify GREEN**

Run:

```powershell
python -m unittest tests.test_workflow_builder -v
```

Expected: four tests pass with `OK`.

- [ ] **Step 5: Commit the callback contract**

```powershell
git add agents/src/utils/workflow_builder.py tests/test_workflow_builder.py
git commit -m "feat: expose incremental workflow results"
```

### Task 2: Add Session Detail and Partial-Result Contracts

**Files:**
- Create: `tests/test_analysis_session_api.py`
- Modify: `backend/server.py`

- [ ] **Step 1: Write failing tests for summaries and partial results**

Create `tests/test_analysis_session_api.py`:

```python
import os
import sys
import unittest
from fastapi.testclient import TestClient

PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, PROJECT_ROOT)
sys.path.insert(0, os.path.join(PROJECT_ROOT, "agents"))

from backend import server


class TestAnalysisSessionApi(unittest.TestCase):
    def setUp(self):
        server.analysis_sessions.clear()
        self.client = TestClient(server.app)
        self.session = server.AnalysisStatus(
            analysis_id="session1",
            status="running",
            progress={
                "fundamental": "completed",
                "technical": "running",
                "value": "waiting",
                "news": "waiting",
                "summary": "waiting",
            },
            agent_details=server.new_agent_details(),
            partial_results={"fundamental_analysis": "# 基本面\n\n盈利能力保持稳健。"},
        )
        self.session.agent_details["fundamental"].update({
            "status": "completed",
            "summary": "盈利能力保持稳健。",
            "result_available": True,
            "execution_time_ms": 48000,
        })
        server.analysis_sessions["session1"] = self.session

    def tearDown(self):
        server.analysis_sessions.clear()

    def test_status_includes_agent_details_and_current_task(self):
        response = self.client.get("/api/status/session1")
        self.assertEqual(response.status_code, 200)
        payload = response.json()
        self.assertEqual(payload["agent_details"]["fundamental"]["summary"], "盈利能力保持稳健。")
        self.assertIn("current_task", payload)

    def test_partial_endpoint_returns_only_completed_results(self):
        response = self.client.get("/api/analysis/session1/partial")
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()["results"], {
            "fundamental_analysis": "# 基本面\n\n盈利能力保持稳健。"
        })

    def test_summary_uses_first_non_heading_paragraph(self):
        text = "# 标题\n\n**结论**\n\n盈利能力保持稳健，现金流良好。\n\n后续详情。"
        self.assertEqual(server.summarize_agent_text(text), "盈利能力保持稳健，现金流良好。")
```

- [ ] **Step 2: Run the test and verify RED**

Run:

```powershell
python -m unittest tests.test_analysis_session_api -v
```

Expected: import or attribute failures for `new_agent_details`, `agent_details`, `partial_results`, and `summarize_agent_text`.

- [ ] **Step 3: Extend `AnalysisStatus` and add helpers**

Add fields and constants in `backend/server.py`:

```python
from typing import Optional, Dict, Any

AGENT_RESULT_KEYS = {
    "fundamental": ("fundamental_analysis", "fundamental_analysis_error"),
    "technical": ("technical_analysis", "technical_analysis_error"),
    "value": ("value_analysis", "value_analysis_error"),
    "news": ("news_analysis", "news_analysis_error"),
    "summary": ("final_report", "summary_error"),
}

def new_agent_details() -> Dict[str, Dict[str, Any]]:
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

from pydantic import BaseModel, Field, field_validator

class AnalysisStatus(BaseModel):
    analysis_id: str
    status: str
    progress: Dict[str, str]
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
```

Add deterministic summary extraction:

```python
def summarize_agent_text(text: str, limit: int = 180) -> str:
    for block in re.split(r"\n\s*\n", text or ""):
        cleaned = re.sub(r"^[#>*\-\s]+", "", block).strip()
        if cleaned and not cleaned.endswith("：") and len(cleaned) >= 8:
            return cleaned[:limit] + ("…" if len(cleaned) > limit else "")
    return ""
```

- [ ] **Step 4: Return the extended status and partial endpoint**

Update `/api/status/{analysis_id}` to include:

```python
"agent_details": session.agent_details,
"current_task": session.current_task,
```

Add:

```python
@app.get("/api/analysis/{analysis_id}/partial")
async def get_partial_results(analysis_id: str):
    session = analysis_sessions.get(analysis_id)
    if session is None:
        raise HTTPException(status_code=404, detail="Analysis not found")
    return {"analysis_id": analysis_id, "results": session.partial_results}
```

- [ ] **Step 5: Run API contract tests and verify GREEN**

Run:

```powershell
python -m unittest tests.test_analysis_session_api -v
```

Expected: three tests pass with `OK`.

- [ ] **Step 6: Commit the session contract**

```powershell
git add backend/server.py tests/test_analysis_session_api.py
git commit -m "feat: expose incremental analysis session data"
```

### Task 3: Persist Each Agent Result During the Workflow

**Files:**
- Modify: `tests/test_analysis_session_api.py`
- Modify: `backend/server.py`
- Modify: `tests/test_end_to_end.py`

- [ ] **Step 1: Write a failing result-persistence test**

Add:

```python
def test_record_agent_result_persists_summary_and_error(self):
    now = "2026-08-10T12:00:00"
    self.session.agent_details["fundamental"]["started_at"] = now
    server.record_agent_result(
        self.session,
        "fundamental",
        {"data": {"fundamental_analysis": "# 结论\n\n盈利能力保持稳健。"}},
        completed_at=now,
    )
    detail = self.session.agent_details["fundamental"]
    self.assertEqual(detail["status"], "completed")
    self.assertTrue(detail["result_available"])
    self.assertEqual(self.session.partial_results["fundamental_analysis"], "# 结论\n\n盈利能力保持稳健。")

    server.record_agent_result(
        self.session,
        "news",
        {"data": {"news_analysis_error": "新闻源不可用"}},
        completed_at=now,
    )
    self.assertEqual(self.session.agent_details["news"]["status"], "failed")
    self.assertEqual(self.session.progress["news"], "failed")
```

- [ ] **Step 2: Run the focused test and verify RED**

Run:

```powershell
python -m unittest tests.test_analysis_session_api.TestAnalysisSessionApi.test_record_agent_result_persists_summary_and_error -v
```

Expected: failure because `record_agent_result` does not exist.

- [ ] **Step 3: Implement lifecycle recording**

Add `mark_agent_status` and `record_agent_result` in `backend/server.py`. `mark_agent_status` stores start timestamps and human-readable current tasks. `record_agent_result` maps the agent to the result/error keys, copies completed text into `partial_results`, derives the summary, records elapsed milliseconds, and changes the progress value to `failed` when the agent returned its error key.

```python
AGENT_TASK_LABELS = {
    "fundamental": "正在分析财务表现与经营质量",
    "technical": "正在分析价格趋势与关键价位",
    "value": "正在比较历史估值分位与行业水平",
    "news": "正在检索新闻、公告与风险事件",
    "summary": "正在汇总四路研究并生成综合结论",
}

def mark_agent_status(session, agent_key: str, status: str) -> None:
    now = datetime.now().isoformat()
    detail = session.agent_details[agent_key]
    if status == "running":
        detail.update({"status": "running", "started_at": now, "error": None})
        session.progress[agent_key] = "running"
        session.current_task = AGENT_TASK_LABELS[agent_key]
    elif status == "completed" and detail["status"] != "failed":
        detail["status"] = "completed"
        detail["completed_at"] = detail["completed_at"] or now
        session.progress[agent_key] = "completed"

def record_agent_result(session, agent_key: str, result: dict, completed_at=None) -> None:
    result_key, error_key = AGENT_RESULT_KEYS[agent_key]
    data = dict((result or {}).get("data", {}))
    detail = session.agent_details[agent_key]
    finished = completed_at or datetime.now().isoformat()
    detail["completed_at"] = finished
    if detail.get("started_at"):
        start = datetime.fromisoformat(detail["started_at"])
        end = datetime.fromisoformat(finished)
        detail["execution_time_ms"] = max(0, int((end - start).total_seconds() * 1000))
    if data.get(error_key):
        detail.update({"status": "failed", "error": str(data[error_key]), "summary": "", "result_available": False})
        session.progress[agent_key] = "failed"
        return
    text = str(data.get(result_key, "") or "")
    if text:
        session.partial_results[result_key] = text
    detail.update({"status": "completed", "error": None, "summary": summarize_agent_text(text), "result_available": bool(text)})
    session.progress[agent_key] = "completed"
```

Use this result callback in `run_analysis_workflow`:

```python
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
```

Store `initial_data` on the session before invoking the graph. After the graph returns, set status to `degraded` when any of the first four details is `failed`; otherwise set it to `completed`.

- [ ] **Step 4: Extend result access for degraded sessions**

Change `/api/result/{analysis_id}` and PDF guards from:

```python
if session.status != "completed":
```

to:

```python
if session.status not in {"completed", "degraded"}:
```

The final report must include a `missing_dimensions` list derived from failed agent keys.

- [ ] **Step 5: Assert callback changes in the end-to-end test**

In `test_full_workflow_produces_report`, pass a result callback that appends agent keys and assert:

```python
self.assertEqual(
    set(result_keys),
    {"fundamental", "technical", "value", "news", "summary"},
)
```

- [ ] **Step 6: Run session, workflow, and end-to-end tests**

Run:

```powershell
python -m unittest tests.test_analysis_session_api tests.test_workflow_builder -v
python -m unittest tests.test_end_to_end -v
```

Expected: all tests in both commands pass with `OK`.

- [ ] **Step 7: Commit incremental persistence**

```powershell
git add backend/server.py tests/test_analysis_session_api.py tests/test_end_to_end.py
git commit -m "feat: persist agent results during analysis"
```

### Task 4: Add Structured Individual-Stock Market Data

**Files:**
- Create: `backend/market_data.py`
- Create: `tests/test_market_data.py`
- Modify: `backend/server.py`

- [ ] **Step 1: Write failing market-data tests**

Create `tests/test_market_data.py` with rows represented as dictionaries:

```python
import unittest
from backend.market_data import normalize_stock_code, build_market_payload


class TestMarketData(unittest.TestCase):
    def test_normalize_stock_code(self):
        self.assertEqual(normalize_stock_code("600519"), "sh.600519")
        self.assertEqual(normalize_stock_code("000001"), "sz.000001")
        self.assertEqual(normalize_stock_code("sh.600519"), "sh.600519")
        with self.assertRaises(ValueError):
            normalize_stock_code("123")

    def test_payload_calculates_moving_averages(self):
        rows = [
            {"date": f"2026-08-{day:02d}", "open": str(day), "high": str(day + 1),
             "low": str(day - 1), "close": str(day), "volume": "1000",
             "turn": "0.2", "pctChg": "1.0", "peTTM": "24.6", "pbMRQ": "8.1"}
            for day in range(1, 22)
        ]
        payload = build_market_payload("sh.600519", rows)
        self.assertTrue(payload["ok"])
        self.assertEqual(payload["latest_trade_date"], "2026-08-21")
        self.assertEqual(payload["candles"][4]["ma5"], 3.0)
        self.assertEqual(payload["candles"][20]["ma20"], 11.5)
        self.assertEqual(payload["quote"]["pe_ttm"], 24.6)

    def test_empty_rows_return_explicit_unavailable_payload(self):
        payload = build_market_payload("sh.600519", [])
        self.assertFalse(payload["ok"])
        self.assertEqual(payload["error"], "未获取到个股行情数据")
```

- [ ] **Step 2: Run market tests and verify RED**

Run:

```powershell
python -m unittest tests.test_market_data -v
```

Expected: import failure because `backend.market_data` does not exist.

- [ ] **Step 3: Implement normalization, moving averages, and BaoStock fetch**

Create `backend/market_data.py` with:

```python
FIELDS = "date,open,high,low,close,volume,turn,pctChg,peTTM,pbMRQ"
ALLOWED_FREQUENCIES = {"d", "w", "m"}

def normalize_stock_code(code: str) -> str:
    value = (code or "").strip().lower()
    if value.startswith(("sh.", "sz.")) and len(value) == 9:
        return value
    if len(value) == 6 and value.isdigit() and value[0] in "036":
        return f"{'sh' if value[0] == '6' else 'sz'}.{value}"
    raise ValueError("股票代码格式无效")

def moving_average(values, window):
    result = []
    for index in range(len(values)):
        if index + 1 < window:
            result.append(None)
        else:
            chunk = values[index + 1 - window:index + 1]
            result.append(round(sum(chunk) / window, 4))
    return result
```

Implement `build_market_payload(code, rows)` using numeric conversion that maps blank strings to `None`. Implement `fetch_stock_market(code, days, frequency, ensure_logged_in, safe_query, bs)` so tests can call the pure payload builder while the server injects existing BaoStock helpers.

- [ ] **Step 4: Add the API endpoint**

In `backend/server.py`, add:

```python
@app.get("/api/stock-market")
async def stock_market(code: str, days: int = 120, frequency: str = "d"):
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
        return {"ok": False, "error": str(exc)}
```

- [ ] **Step 5: Add a patched TestClient endpoint test**

Add this test to `tests/test_analysis_session_api.py`:

```python
def test_stock_market_endpoint_returns_structured_payload(self):
    from unittest.mock import patch

    payload = {
        "ok": True,
        "code": "sh.600519",
        "latest_trade_date": "2026-08-07",
        "quote": {"close": 1482.5, "pct_change": 1.28},
        "candles": [
            {"time": "2026-08-06", "open": 1460, "high": 1480, "low": 1450, "close": 1470, "volume": 100, "ma5": None, "ma20": None},
            {"time": "2026-08-07", "open": 1470, "high": 1490, "low": 1462, "close": 1482.5, "volume": 120, "ma5": None, "ma20": None},
        ],
    }
    with patch.object(server, "fetch_stock_market", return_value=payload):
        response = self.client.get("/api/stock-market?code=600519")
    self.assertEqual(response.status_code, 200)
    self.assertEqual(response.json(), payload)
```

- [ ] **Step 6: Run market and API tests**

Run:

```powershell
python -m unittest tests.test_market_data tests.test_analysis_session_api -v
```

Expected: all tests pass with `OK`.

- [ ] **Step 7: Commit market data support**

```powershell
git add backend/market_data.py backend/server.py tests/test_market_data.py tests/test_analysis_session_api.py
git commit -m "feat: add structured stock market data"
```

### Task 5: Add Degraded-State Retry

**Files:**
- Modify: `tests/test_analysis_session_api.py`
- Modify: `backend/server.py`

- [ ] **Step 1: Write failing retry-validation tests**

Add this test after setting the session to degraded with a failed `news` detail:

```python
def test_retry_accepts_only_failed_analysis_agents(self):
    from unittest.mock import AsyncMock, patch

    self.session.status = "degraded"
    self.session.agent_details["news"]["status"] = "failed"
    with patch.object(server, "retry_agent_and_summary", new=AsyncMock()):
        response = self.client.post("/api/analysis/session1/retry/news")
    self.assertEqual(response.status_code, 202)
    self.assertEqual(response.json()["status"], "retrying")

    response = self.client.post("/api/analysis/session1/retry/fundamental")
    self.assertEqual(response.status_code, 409)

    response = self.client.post("/api/analysis/session1/retry/summary")
    self.assertEqual(response.status_code, 422)
```

Patch `backend.server.retry_agent_and_summary` with `AsyncMock` so the endpoint test does not call an LLM.

- [ ] **Step 2: Run retry tests and verify RED**

Run:

```powershell
python -m unittest tests.test_analysis_session_api -v
```

Expected: 404 for the missing retry route.

- [ ] **Step 3: Implement retry validation and execution**

Add:

```python
RETRYABLE_AGENTS = {
    "fundamental": fundamental_agent,
    "technical": technical_agent,
    "value": value_agent,
    "news": news_agent,
}
```

The endpoint must reject unknown/non-retryable agents, reject non-failed agents with 409, set the chosen detail to `running`, and schedule `retry_agent_and_summary` with `asyncio.create_task`.

`retry_agent_and_summary` must:

1. Build an `AgentState` from `session.initial_data` and `session.partial_results`.
2. Await the selected agent.
3. Call `record_agent_result`.
4. If successful, invoke `summary_agent` with all available partials.
5. Rebuild `session.result`, `missing_dimensions`, and final `completed`/`degraded` status.
6. On exception, retain other partials and set only the retried detail back to `failed`.

Implement the helper with injectable agent functions so its test remains network-free:

```python
async def retry_agent_and_summary(
    analysis_id: str,
    agent_key: str,
    selected_agent=None,
    summarizer=None,
):
    session = analysis_sessions[analysis_id]
    agent_fn = selected_agent or RETRYABLE_AGENTS[agent_key]
    summary_fn = summarizer or summary_agent
    try:
        state = AgentState(
            messages=[],
            data={**session.initial_data, **session.partial_results},
            metadata={"analysis_id": analysis_id, "retry": agent_key},
        )
        mark_agent_status(session, agent_key, "running")
        agent_result = await agent_fn(state)
        record_agent_result(session, agent_key, agent_result)
        if session.agent_details[agent_key]["status"] == "failed":
            session.status = "degraded"
            return
        summary_state = AgentState(
            messages=[],
            data={**session.initial_data, **session.partial_results},
            metadata={"analysis_id": analysis_id, "retry": agent_key},
        )
        mark_agent_status(session, "summary", "running")
        summary_result = await summary_fn(summary_state)
        record_agent_result(session, "summary", summary_result)
        rebuild_session_result(session)
    except Exception as exc:
        session.agent_details[agent_key].update({"status": "failed", "error": str(exc)})
        session.progress[agent_key] = "failed"
        session.status = "degraded"
```

- [ ] **Step 4: Test helper behavior with fake agents**

Add this network-free helper test:

```python
def test_retry_helper_replaces_failed_dimension_and_reruns_summary(self):
    import asyncio

    self.session.status = "degraded"
    self.session.initial_data = {"query": "贵州茅台", "stock_code": "sh.600519"}
    self.session.partial_results = {"fundamental_analysis": "基本面结果"}
    self.session.agent_details["news"]["status"] = "failed"
    summary_inputs = []

    async def fake_news(state):
        return {"data": {**state["data"], "news_analysis": "新闻重试结果"}}

    async def fake_summary(state):
        summary_inputs.append(dict(state["data"]))
        return {"data": {**state["data"], "final_report": "重建后的综合报告"}}

    asyncio.run(server.retry_agent_and_summary(
        "session1",
        "news",
        selected_agent=fake_news,
        summarizer=fake_summary,
    ))

    self.assertEqual(self.session.partial_results["fundamental_analysis"], "基本面结果")
    self.assertEqual(self.session.partial_results["news_analysis"], "新闻重试结果")
    self.assertEqual(len(summary_inputs), 1)
    self.assertEqual(summary_inputs[0]["news_analysis"], "新闻重试结果")
```

- [ ] **Step 5: Run API tests and verify GREEN**

Run:

```powershell
python -m unittest tests.test_analysis_session_api -v
```

Expected: all tests pass with `OK`.

- [ ] **Step 6: Commit retry support**

```powershell
git add backend/server.py tests/test_analysis_session_api.py
git commit -m "feat: retry failed analysis dimensions"
```

### Task 6: Build Testable Frontend Workbench State Helpers

**Files:**
- Create: `frontend/workbench.js`
- Create: `tests/frontend/test_workbench.cjs`

- [ ] **Step 1: Write failing Node tests**

Create `tests/frontend/test_workbench.cjs`:

```javascript
const test = require('node:test');
const assert = require('node:assert/strict');
const {
  derivePhase,
  normalizeAgentDetails,
  buildMarketSeries,
  completedResultKeys,
} = require('../../frontend/workbench.js');

test('derivePhase distinguishes partial and summarizing states', () => {
  assert.equal(derivePhase({
    status: 'running',
    progress: { fundamental: 'completed', technical: 'running', value: 'waiting', news: 'waiting', summary: 'waiting' },
  }), 'partial');
  assert.equal(derivePhase({
    status: 'running',
    progress: { fundamental: 'completed', technical: 'completed', value: 'completed', news: 'completed', summary: 'running' },
  }), 'summarizing');
});

test('normalizeAgentDetails supplies safe waiting defaults', () => {
  const details = normalizeAgentDetails({ fundamental: { status: 'completed', summary: '稳健' } });
  assert.equal(details.fundamental.summary, '稳健');
  assert.equal(details.news.status, 'waiting');
});

test('buildMarketSeries preserves real candles and skips missing moving averages', () => {
  const series = buildMarketSeries({ candles: [
    { time: 1, open: 1, high: 2, low: 0.5, close: 1.5, volume: 100, ma5: null, ma20: null },
    { time: 2, open: 1.5, high: 3, low: 1, close: 2.5, volume: 200, ma5: 2, ma20: null },
  ] });
  assert.equal(series.candles.length, 2);
  assert.deepEqual(series.ma5, [{ time: 2, value: 2 }]);
  assert.equal(series.volume[1].value, 200);
});

test('completedResultKeys returns only newly available completed dimensions', () => {
  assert.deepEqual(
    completedResultKeys({ fundamental: 'completed', technical: 'running' }, new Set()),
    ['fundamental'],
  );
});
```

- [ ] **Step 2: Run Node tests and verify RED**

Run:

```powershell
node --test tests/frontend/test_workbench.cjs
```

Expected: module-not-found failure for `frontend/workbench.js`.

- [ ] **Step 3: Implement pure helpers and UMD export**

Create `frontend/workbench.js` using a UMD wrapper:

```javascript
(function (root, factory) {
  const api = factory();
  if (typeof module === 'object' && module.exports) module.exports = api;
  else root.FinexWorkbench = api;
})(typeof globalThis !== 'undefined' ? globalThis : this, function () {
  const AGENTS = ['fundamental', 'technical', 'value', 'news', 'summary'];

  function normalizeAgentDetails(input = {}) {
    return Object.fromEntries(AGENTS.map((key) => [key, {
      status: 'waiting', summary: '', error: null,
      result_available: false, execution_time_ms: null,
      ...(input[key] || {}),
    }]));
  }

  function derivePhase(payload) {
    if (payload.status === 'completed') return 'completed';
    if (payload.status === 'degraded') return 'degraded';
    if (payload.status === 'error') return 'error';
    const values = payload.progress || {};
    if (values.summary === 'running') return 'summarizing';
    if (AGENTS.some((key) => values[key] === 'completed')) return 'partial';
    return payload.status === 'running' ? 'running' : 'starting';
  }

  function buildMarketSeries(payload = {}) {
    const candles = Array.isArray(payload.candles) ? payload.candles : [];
    return {
      candles: candles.map(({ time, open, high, low, close }) => ({ time, open, high, low, close })),
      volume: candles.map(({ time, volume, close, open }) => ({
        time,
        value: Number(volume || 0),
        color: close >= open ? '#557a66' : '#a0473e',
      })),
      ma5: candles.filter((row) => row.ma5 != null).map(({ time, ma5 }) => ({ time, value: ma5 })),
      ma20: candles.filter((row) => row.ma20 != null).map(({ time, ma20 }) => ({ time, value: ma20 })),
    };
  }

  function completedResultKeys(progress = {}, seen = new Set()) {
    return AGENTS.filter((key) => key !== 'summary' && progress[key] === 'completed' && !seen.has(key));
  }

  return { AGENTS, normalizeAgentDetails, derivePhase, buildMarketSeries, completedResultKeys };
});
```

- [ ] **Step 4: Run Node tests and verify GREEN**

Run:

```powershell
node --test tests/frontend/test_workbench.cjs
```

Expected: four tests pass, zero fail.

- [ ] **Step 5: Commit frontend state helpers**

```powershell
git add frontend/workbench.js tests/frontend/test_workbench.cjs
git commit -m "feat: add workbench state helpers"
```

### Task 7: Replace the Analysis Page with the Confirmed Workbench Markup and Styling

**Files:**
- Create: `frontend/workbench.css`
- Modify: `frontend/index.html`
- Modify: `frontend/workbench.js`
- Modify: `tests/frontend/test_workbench.cjs`

- [ ] **Step 1: Write a failing static workbench contract test**

Add a Node test that reads `frontend/index.html` and asserts all required IDs exist:

```javascript
const fs = require('node:fs');
const path = require('node:path');

test('index contains one in-place workbench and all five agent cards', () => {
  const html = fs.readFileSync(path.join(__dirname, '../../frontend/index.html'), 'utf8');
  assert.match(html, /id="analysisWorkbench"/);
  assert.match(html, /id="workbenchMarketChart"/);
  assert.match(html, /data-agent="fundamental"/);
  assert.match(html, /data-agent="technical"/);
  assert.match(html, /data-agent="value"/);
  assert.match(html, /data-agent="news"/);
  assert.match(html, /data-agent="summary"/);
  assert.doesNotMatch(html, /id="goToReportBtn"/);
});
```

- [ ] **Step 2: Run the static test and verify RED**

Run:

```powershell
node --test tests/frontend/test_workbench.cjs
```

Expected: failure because `analysisWorkbench` and `workbenchMarketChart` are missing.

- [ ] **Step 3: Add static assets to `index.html`**

In `<head>` add:

```html
<link rel="stylesheet" href="/static/workbench.css">
```

Before the existing bottom inline script add:

```html
<script src="/static/workbench.js"></script>
```

- [ ] **Step 4: Replace the old analysis/report sections**

Preserve compatibility IDs used by the existing lifecycle (`analysisSection`, `analyzingStock`, `elapsedTime`, `statusText`, `backBtn`, `downloadPdfBtn`, `pdfBtnText`, `pdfSpinner`, `newAnalysisBtn`, and `backToHomeBtn`). Add:

```html
<section class="analysis-section workbench-section" id="analysisSection">
  <div class="analysis-workbench" id="analysisWorkbench">
    <header class="workbench-masthead">
      <button class="workbench-back" id="backBtn" type="button">返回首页</button>
      <div><span class="workbench-eyebrow">FINEX RESEARCH</span><h1 id="analyzingStock">股票研究</h1></div>
      <div class="workbench-meta"><span id="elapsedTime">00:00</span><span id="statusText">准备中</span></div>
    </header>
    <div class="workbench-layout" id="workbenchRunningState">
      <main class="agent-workspace">
        <div class="agent-grid" id="agentGrid">
          <article class="workbench-agent-card" data-agent="fundamental"><h2>基本面分析师</h2><p class="agent-summary"></p><div class="agent-microchart"></div><button class="agent-retry" type="button" hidden>重试该项</button></article>
          <article class="workbench-agent-card" data-agent="technical"><h2>技术面分析师</h2><p class="agent-summary"></p><div class="agent-microchart"></div><button class="agent-retry" type="button" hidden>重试该项</button></article>
          <article class="workbench-agent-card" data-agent="value"><h2>估值分析师</h2><p class="agent-summary"></p><div class="agent-microchart"></div><button class="agent-retry" type="button" hidden>重试该项</button></article>
          <article class="workbench-agent-card" data-agent="news"><h2>新闻分析师</h2><p class="agent-summary"></p><div class="agent-microchart"></div><button class="agent-retry" type="button" hidden>重试该项</button></article>
          <article class="workbench-agent-card agent-card-summary" data-agent="summary"><h2>综合研判</h2><p class="agent-summary"></p><div class="agent-microchart agent-summary-chart"></div></article>
        </div>
      </main>
      <aside class="market-overview">
        <div class="market-header"><h2>行情概览</h2><span id="marketTradeDate">最新交易日</span></div>
        <div class="market-periods"><button type="button" data-frequency="d" aria-pressed="true">日 K</button><button type="button" data-frequency="w" aria-pressed="false">周 K</button><button type="button" data-frequency="m" aria-pressed="false">月 K</button></div>
        <div id="workbenchMarketChart" class="workbench-market-chart" role="img" aria-label="个股行情图加载中"></div>
        <dl class="market-metrics" id="marketMetrics"></dl>
      </aside>
    </div>
    <div class="workbench-report" id="workbenchReport" hidden>
      <nav id="reportNavigation" aria-label="报告章节"></nav>
      <main id="reportContent"></main>
      <div class="report-actions"><button id="backToHomeBtn" type="button">返回首页</button><button id="downloadPdfBtn" type="button" disabled><span id="pdfSpinner"></span><span id="pdfBtnText">正在生成 PDF</span></button><button id="newAnalysisBtn" type="button">新分析</button></div>
    </div>
  </div>
</section>
```

Remove the separate `reportSection` and dynamic fixed `goToReportBtn` behavior. The report container now lives inside the workbench.

- [ ] **Step 5: Implement the confirmed visual system in `workbench.css`**

Use these fixed design tokens:

```css
:root {
  --wb-paper: #e7ddcc;
  --wb-paper-raised: rgba(250, 245, 236, 0.82);
  --wb-ink: #2b241b;
  --wb-muted: #74695b;
  --wb-gold: #806127;
  --wb-line: #b6a78e;
  --wb-serif: "Noto Serif SC", "Source Han Serif SC", "Songti SC", serif;
}
```

Implement these structural rules, then add the confirmed typography, surface, micro-chart, and state styles using the tokens above:

```css
.workbench-layout {
  display: grid;
  grid-template-columns: minmax(0, 1.55fr) minmax(280px, .65fr);
  gap: 1.5rem;
}
.agent-grid { display: grid; grid-template-columns: repeat(2, minmax(0, 1fr)); gap: .75rem; }
.agent-card-summary { grid-column: 1 / -1; }
.workbench-agent-card {
  min-height: 220px;
  padding: 1rem;
  border: 1px solid color-mix(in srgb, var(--wb-gold) 28%, transparent);
  border-radius: 20px;
  background: var(--wb-paper-raised);
  box-shadow: 0 9px 22px rgba(65, 47, 24, .07);
  transition: transform .3s ease, box-shadow .3s ease;
}
.workbench-agent-card:hover { transform: translateY(-4px); box-shadow: 0 17px 34px rgba(65, 47, 24, .13); }
.workbench-agent-card h2 { font: 600 15px/1.5 var(--wb-serif); }
.agent-summary { font: 400 13px/1.75 var(--wb-serif); }
.agent-microchart { min-height: 80px; }
.agent-summary-chart { min-height: 150px; }
@media (max-width: 768px) { .workbench-layout { grid-template-columns: 1fr; } }
@media (max-width: 720px) { .agent-grid { grid-template-columns: 1fr; } .agent-card-summary { grid-column: auto; } }
@media (prefers-reduced-motion: reduce) { .workbench-agent-card { transition: none; animation: none; } }
```

Additional required rules:

- Desktop `.workbench-layout`: analysis column plus market column.
- `.agent-grid`: two equal columns.
- `.agent-card-summary`: span both columns.
- Cards: 18–20px radius, translucent warm surface, no overlap.
- Card title 15px, summary 13px, tags 11px, important values 18px.
- Per-agent micro-visual area: minimum 80px.
- Summary micro-visual area: 150px.
- Hover lift no more than 4px.
- Active card bottom scan strip and status pulse.
- At `max-width: 720px`, switch to one column and make summary span one column.
- Under `prefers-reduced-motion: reduce`, remove stagger, pulse, scan, and layout animations.

- [ ] **Step 6: Add controller selectors and render methods**

Extend `frontend/workbench.js` with `createController(root, options)`. It must expose:

```javascript
{
  reset(stockLabel),
  updateStatus(payload),
  updatePartialResults(results),
  renderMarket(payload),
  renderReport(result),
  renderError(message),
  destroy(),
}
```

The controller must use `textContent` for status, labels, metrics, summaries, and errors. Long analysis Markdown remains in the existing trusted report rendering path; do not inject API error strings with `innerHTML`.

- [ ] **Step 7: Run frontend tests and verify GREEN**

Run:

```powershell
node --test tests/frontend/test_workbench.cjs
```

Expected: all tests pass, including the static markup contract.

- [ ] **Step 8: Commit workbench structure and styles**

```powershell
git add frontend/index.html frontend/workbench.css frontend/workbench.js tests/frontend/test_workbench.cjs
git commit -m "feat: build stock analysis workbench"
```

### Task 8: Wire Polling, Partial Results, Market Data, and In-Place Completion

**Files:**
- Modify: `frontend/index.html`
- Modify: `frontend/workbench.js`
- Modify: `tests/frontend/test_workbench.cjs`

- [ ] **Step 1: Write failing controller decision tests**

Add tests for a pure `nextRequests(previousProgress, payload)` helper:

```javascript
test('nextRequests fetches partials only when a dimension newly completes', () => {
  const requests = nextRequests(
    { fundamental: 'running', technical: 'running' },
    { progress: { fundamental: 'completed', technical: 'running' } },
  );
  assert.deepEqual(requests, { partial: true, result: false });
});

test('nextRequests fetches final result for completed or degraded sessions', () => {
  assert.deepEqual(
    nextRequests({}, { status: 'degraded', progress: {} }),
    { partial: false, result: true },
  );
});
```

- [ ] **Step 2: Run Node tests and verify RED**

Run:

```powershell
node --test tests/frontend/test_workbench.cjs
```

Expected: `nextRequests is not defined`.

- [ ] **Step 3: Implement request decisions and lifecycle wiring**

Update the existing functions in `index.html`:

- `startAnalysis` calls `workbench.reset(input)` before the API request.
- Once `/api/analyze` returns, fetch `/api/stock-market` after the normalized code becomes available in status or partial metadata. Until then, show an explicit loading state in the market panel.
- `handlePollStatus` passes every payload to `workbench.updateStatus`.
- When `nextRequests` says `partial`, fetch `/api/analysis/{id}/partial` once and call `updatePartialResults`.
- When status is `completed` or `degraded`, fetch `/api/result/{id}` and call `renderReport` directly.
- Remove `showReportButton`; completion must not create a fixed button.
- Keep PDF polling and history refresh behavior.
- For a failed detail, its retry button posts to `/api/analysis/{id}/retry/{agent}` and resumes polling.

- [ ] **Step 4: Render real market data with Lightweight Charts**

In `renderMarket`, create or update:

- Candlestick series from `series.candles`.
- Histogram series from `series.volume`.
- Gold MA5 line from `series.ma5`.
- Muted blue-gray MA20 line from `series.ma20`.

Render `latest_trade_date` visibly. Never label the payload real-time. On `{ok: false}`, show “行情数据暂不可用” and keep agent analysis active.

- [ ] **Step 5: Run frontend tests and verify GREEN**

Run:

```powershell
node --test tests/frontend/test_workbench.cjs
```

Expected: all tests pass.

- [ ] **Step 6: Run backend API tests**

Run:

```powershell
python -m unittest tests.test_analysis_session_api tests.test_market_data tests.test_workflow_builder -v
```

Expected: all tests pass with `OK`.

- [ ] **Step 7: Commit lifecycle integration**

```powershell
git add frontend/index.html frontend/workbench.js tests/frontend/test_workbench.cjs
git commit -m "feat: stream analysis progress into workbench"
```

### Task 9: Add Browser-Level Accessibility and Responsive Verification

**Files:**
- Create: `tests/frontend/workbench-smoke.spec.js`
- Modify: `frontend/workbench.css`
- Modify: `frontend/index.html`

- [ ] **Step 1: Write a Playwright smoke test before final polish**

Create `tests/frontend/workbench-smoke.spec.js` that routes API calls with deterministic fixtures, opens `http://127.0.0.1:8100`, starts a `600519` analysis, and asserts:

```javascript
await expect(page.locator('[data-agent]')).toHaveCount(5);
await expect(page.locator('[data-agent="summary"]')).toBeVisible();
await expect(page.locator('#workbenchMarketChart')).toBeVisible();
await expect(page.locator('#workbenchReport')).toBeHidden();
```

After returning a completed status/result fixture:

```javascript
await expect(page.locator('#workbenchReport')).toBeVisible();
await expect(page.locator('#goToReportBtn')).toHaveCount(0);
```

- [ ] **Step 2: Run the browser smoke test and verify RED**

Start the server:

```powershell
python backend/server.py
```

In another terminal, run the project’s bundled Playwright wrapper according to the `playwright` skill, targeting `tests/frontend/workbench-smoke.spec.js`.

Expected: at least one visibility, responsive, or completion assertion fails before browser polish.

- [ ] **Step 3: Fix accessibility and responsive gaps**

Ensure:

- Retry controls are real `<button>` elements with visible labels.
- Agent status includes text and does not rely on color.
- Chart container has `role="img"` and an updated `aria-label` with date range.
- Period choices are buttons with `aria-pressed`.
- Interactive targets are at least 44 × 44px.
- At 390px, cards are single-column with no horizontal overflow.
- At 768px, the market panel moves below the grid when two columns become too narrow.
- At 1440px, the 2 × 2 + 1 grid and market panel remain balanced.

- [ ] **Step 4: Run smoke test at desktop and mobile widths**

Run the smoke test at 1440 × 1000, 768 × 1024, and 390 × 844.

Expected: all assertions pass and screenshots show no overlap, clipping, or unreadably small text.

- [ ] **Step 5: Commit browser polish**

```powershell
git add frontend/index.html frontend/workbench.css tests/frontend/workbench-smoke.spec.js
git commit -m "test: verify workbench responsive experience"
```

### Task 10: Run Full Regression and Final Visual QA

**Files:**
- Modify only files needed to fix failures discovered by this task.

- [ ] **Step 1: Run focused backend suites**

```powershell
python -m unittest tests.test_workflow_builder tests.test_analysis_session_api tests.test_market_data tests.test_api_config -v
```

Expected: all tests pass with `OK`.

- [ ] **Step 2: Run concurrency and agent failure suites**

```powershell
python -m unittest tests.test_baostock_concurrency tests.test_agent_failure_handling -v
```

Expected: all tests pass with `OK`.

- [ ] **Step 3: Run the isolated end-to-end suite**

```powershell
python -m unittest tests.test_end_to_end -v
```

Expected: all tests pass with `OK`.

- [ ] **Step 4: Run frontend unit tests**

```powershell
node --test tests/frontend/test_workbench.cjs
```

Expected: all tests pass, zero fail.

- [ ] **Step 5: Run browser smoke and inspect screenshots**

Verify all three target widths and both `prefers-reduced-motion` settings. Confirm:

- Five cards are visible and never overlap.
- Chinese serif typography is loaded or falls back without layout shift.
- Micro charts are at least 80px; the summary graphic is about 150px.
- Market chart includes candles, volume, MA5, and MA20.
- Partial results appear without a full-page refresh.
- Completed and degraded sessions show the report in place.
- No fake progress percentage or fake market values are displayed.

- [ ] **Step 6: Check diff quality and scope**

```powershell
git diff --check
git status --short
git log --oneline -10
```

Expected: no whitespace errors; only planned workbench/backend/test files are modified; commits are task-scoped.

- [ ] **Step 7: Commit any final verified fixes**

If Step 1–6 required fixes, stage only those files and commit:

```powershell
git commit -m "fix: finalize stock analysis workbench"
```

If no fixes were needed, do not create an empty commit.
