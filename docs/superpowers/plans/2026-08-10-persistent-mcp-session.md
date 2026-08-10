# Persistent MCP Session Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Reuse one MCP stdio session for all analysis tools so four parallel analysts finish within the existing 480-second limit without Baostock session corruption.

**Architecture:** `mcp_client.py` owns one explicit `ClientSession` for the FastAPI event loop and loads LangChain tools against that session. Existing tool serialization remains around calls, but no longer includes subprocess creation. Frequency-aware K-line fields and bounded latest-quarter fallback remove avoidable ReAct retries.

**Tech Stack:** Python 3.10+, asyncio, LangChain MCP adapters, FastMCP, Baostock 0.9.3, unittest.

## Global Constraints

- Keep four analyst agents parallel and keep `REACT_TIMEOUT_SECONDS=480`.
- Keep `MCP_TOOL_TIMEOUT_SECONDS=45`.
- Do not change the configured LLM or automatically start a paid analysis.
- Run all implementation in `E:\Curzsu\Finance1\.worktrees\stock-analysis-workbench` on branch `codex/stock-analysis-workbench`.

---

### Task 1: Persistent MCP session lifecycle

**Files:**
- Modify: `agents/src/tools/mcp_client.py`
- Modify: `tests/test_mcp_tool_serialization.py`

**Interfaces:**
- Consumes: `MultiServerMCPClient.session("a_share_mcp_v2")` and `load_mcp_tools(session)`.
- Produces: `get_mcp_tools() -> list[BaseTool]` bound to one live session; `close_mcp_client_sessions() -> None` that exits it once.

- [ ] **Step 1: Write the failing reuse test**

Add an async test with a fake client session context and fake `load_mcp_tools`. Call `get_mcp_tools()` twice and assert both calls return the same tools while the context manager is entered exactly once.

- [ ] **Step 2: Run the focused test and verify RED**

Run: `E:\Curzsu\Finance1\venv\Scripts\python.exe tests\test_mcp_tool_serialization.py -v`

Expected: FAIL because `get_mcp_tools()` still calls `client.get_tools()` and does not enter the explicit session.

- [ ] **Step 3: Implement the persistent session**

Import `load_mcp_tools`, add cached `_mcp_session_context`, `_mcp_session`, and `_mcp_session_loop`, then replace `client.get_tools()` with:

```python
session_context = client.session("a_share_mcp_v2")
session = await session_context.__aenter__()
loaded_tools = await load_mcp_tools(session)
```

Cache the context only after tool loading succeeds. On initialization failure, call `__aexit__` for the local context before returning an uncached empty list.

- [ ] **Step 4: Write and run the failing close test**

Call `close_mcp_client_sessions()` twice after initialization and assert the persistent context receives one `__aexit__(None, None, None)` call and all session globals become `None`.

- [ ] **Step 5: Implement close semantics and verify GREEN**

Exit the cached session context before clearing globals. Log exit errors, always clear cached state, and keep repeated close calls idempotent.

Run: `E:\Curzsu\Finance1\venv\Scripts\python.exe tests\test_mcp_tool_serialization.py -v`

Expected: all persistent-session, serialization, and deadline tests PASS.

- [ ] **Step 6: Commit Task 1**

```powershell
git add agents/src/tools/mcp_client.py tests/test_mcp_tool_serialization.py
git commit -m "fix: reuse persistent MCP session"
```

### Task 2: Frequency-aware K-line fields

**Files:**
- Modify: `mcp-server/src/baostock_data_source.py`
- Create: `tests/test_mcp_data_fallbacks.py`

**Interfaces:**
- Produces: `get_k_fields(frequency: str, fields: Optional[list[str]]) -> list[str]`.
- Daily default keeps `DEFAULT_K_FIELDS`; weekly/monthly defaults are exactly `date, code, open, high, low, close, volume, amount, adjustflag`.
- Explicit caller fields remain unchanged.

- [ ] **Step 1: Write the failing field-selection tests**

Assert daily defaults contain `preclose` and `peTTM`; weekly/monthly defaults equal the safe literal list; explicit `['date', 'close']` is preserved.

- [ ] **Step 2: Run the focused test and verify RED**

Run: `E:\Curzsu\Finance1\venv\Scripts\python.exe tests\test_mcp_data_fallbacks.py -v`

Expected: FAIL because `get_k_fields` does not exist.

- [ ] **Step 3: Implement frequency-aware fields**

Add `PERIOD_K_FIELDS` and `get_k_fields`. In `get_historical_k_data`, call `get_k_fields(frequency, fields)` before `_format_fields` so week/month requests never inherit daily-only fields.

- [ ] **Step 4: Verify GREEN and the real weekly query**

Run the focused test, then call `get_historical_k_data` through the MCP adapter with `frequency='w'` and no explicit fields. Assert the returned text does not contain error code `10004012`.

- [ ] **Step 5: Commit Task 2**

```powershell
git add mcp-server/src/baostock_data_source.py tests/test_mcp_data_fallbacks.py
git commit -m "fix: select valid periodic K-line fields"
```

### Task 3: Latest available financial-quarter fallback

**Files:**
- Modify: `mcp-server/src/tools/analysis.py`
- Modify: `tests/test_mcp_data_fallbacks.py`

**Interfaces:**
- Produces: `recent_quarters(now: datetime, limit: int = 8) -> list[tuple[str, int]]`.
- Produces: `fetch_latest_financial_bundle(data_source, code, now=None) -> tuple[str, int, dict[str, DataFrame]]`.
- A candidate quarter is selected only when profitability data exists; growth, balance, and DuPont are then fetched for that same quarter.

- [ ] **Step 1: Write the failing quarter-sequence test**

For `datetime(2026, 8, 10)`, assert the first five candidates are `('2026', 3)`, `('2026', 2)`, `('2026', 1)`, `('2025', 4)`, `('2025', 3)`.

- [ ] **Step 2: Write the failing fallback behavior test**

Use a small fake data source whose profitability call raises `NoDataFoundError` for 2026Q3 and Q2 and returns a one-row DataFrame for 2026Q1. Assert the helper returns 2026Q1 and fetches growth, balance, and DuPont for Q1 only.

- [ ] **Step 3: Run focused tests and verify RED**

Run: `E:\Curzsu\Finance1\venv\Scripts\python.exe tests\test_mcp_data_fallbacks.py -v`

Expected: FAIL because the helpers do not exist.

- [ ] **Step 4: Implement bounded fallback**

Add both helpers. Catch only `NoDataFoundError` while probing profitability; propagate login and API failures. Replace the direct current-quarter calls inside `get_stock_analysis` with the returned bundle.

- [ ] **Step 5: Verify GREEN**

Run: `E:\Curzsu\Finance1\venv\Scripts\python.exe tests\test_mcp_data_fallbacks.py -v`

Expected: all field and quarter fallback tests PASS.

- [ ] **Step 6: Commit Task 3**

```powershell
git add mcp-server/src/tools/analysis.py tests/test_mcp_data_fallbacks.py
git commit -m "fix: fall back to available financial quarter"
```

### Task 4: Integration verification and service restart

**Files:**
- Verify only; no planned production edits.

**Interfaces:**
- Verifies persistent session tools, workflow regressions, API readiness, and PDF runtime.

- [ ] **Step 1: Run Python regressions**

```powershell
E:\Curzsu\Finance1\venv\Scripts\python.exe tests\test_mcp_runtime.py -v
E:\Curzsu\Finance1\venv\Scripts\python.exe tests\test_mcp_tool_serialization.py -v
E:\Curzsu\Finance1\venv\Scripts\python.exe tests\test_mcp_data_fallbacks.py -v
E:\Curzsu\Finance1\venv\Scripts\python.exe tests\test_analysis_session_api.py -v
E:\Curzsu\Finance1\venv\Scripts\python.exe tests\test_workflow_builder.py -v
```

Expected: zero failures.

- [ ] **Step 2: Run frontend regressions and syntax checks**

```powershell
E:\nodejs\node.exe --test tests/frontend/test_workbench.cjs
E:\Curzsu\Finance1\venv\Scripts\python.exe -m py_compile agents\src\tools\mcp_client.py mcp-server\src\baostock_data_source.py mcp-server\src\tools\analysis.py
git diff --check
```

Expected: 23 frontend tests pass, syntax checks exit 0, and no whitespace errors.

- [ ] **Step 3: Run a real persistent-session smoke test**

Open one explicit MCP session, load tools once, and sequentially invoke stock basic info, daily K-line, weekly K-line, industry, and latest trading date for `sh.600036`. Assert every result is non-error and total tool execution stays below 30 seconds.

- [ ] **Step 4: Restart the local server**

Stop only the process listening on port 8100 after verifying its command line, start Uvicorn from the project virtual environment, and verify `/api/config` returns HTTP 200. Do not submit `/api/analyze`.

- [ ] **Step 5: Final status check**

Run `git status --short` and record the latest commits. The worktree must be clean and the server must be listening on port 8100.
