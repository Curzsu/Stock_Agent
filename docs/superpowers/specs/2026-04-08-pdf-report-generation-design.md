# PDF Report Generation Design

## Goal
Add PDF output to the FINEX financial analysis system. MD reports remain unchanged; PDF is generated as a background step after MD is saved.

## Architecture

### Pipeline
```
summary_agent generates MD → MD saved to disk → State returned immediately (pdf_path=None)
  → [Background Task] convert_md_to_pdf(md_path) → PDF saved alongside MD
```

### New Files
- `agents/src/utils/pdf_converter.py` — Async wrapper + sync WeasyPrint conversion
- `agents/src/utils/pdf_styles.py` — CSS template and HTML wrapper for authoritative styling

### Modified Files
- `agents/src/agents/summary_agent.py` — Fire-and-forget PDF task after MD save
- `backend/server.py` — Add `/api/report-pdf/{analysis_id}` endpoint, add `pdf_path` to result
- `frontend/index.html` — Add PDF download button with polling UX
- `requirements.txt` — Add `weasyprint>=60.0`

## Key Design Decisions

### 1. Asynchronous Non-blocking Execution
- `summary_agent` returns immediately with `pdf_path=None`
- PDF generation runs via `asyncio.create_task` + `run_in_executor`
- WeasyPrint (sync/CPU-bound) runs in thread executor, never blocks the event loop

### 2. Exception Isolation
- Layer 1: `convert_md_to_pdf()` wraps WeasyPrint in try-except with specific error logging
- Layer 2: `generate_pdf_background()` catches any escape, ensures `pdf_path=None`
- Layer 3: Frontend gracefully degrades — no download button if PDF unavailable

### 3. File-System-Based Status Tracking (No Database)
- PDF saved in `agents/reports/` with same base name as MD (e.g., `report_123.md` → `report_123.pdf`)
- Backend checks `os.path.exists(pdf_path)` to determine PDF availability
- Frontend polls `/api/result/{id}` until `pdf_available: true`
- No in-memory state needed for PDF status

### 4. Font Dependencies
- CSS specifies: `font-family: "Noto Sans SC", "Microsoft YaHei", "SimSun", sans-serif`
- Setup note in requirements: Ubuntu/Debian needs `fonts-noto-cjk`, Windows usually has pre-installed fonts

## PDF Styling Direction
- Authoritative investment bank research report aesthetic
- Dark header with gold accents matching FINEX brand colors
- Professional typography with clear section hierarchy
- Table of contents, page numbers, watermarks
- Clean borders and spacing between sections

## API Changes

### New Endpoint
- `GET /api/report-pdf/{analysis_id}` — Returns PDF file download if exists, 404 if not ready/unavailable

### Modified Endpoint
- `GET /api/result/{analysis_id}` — Response now includes `pdf_path` and `pdf_available: bool`

## Frontend Changes
- Download PDF button in report view
- Button starts as disabled/hidden, polls until `pdf_available: true`
- Smooth transition when PDF becomes available
