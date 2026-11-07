"""Read one FINEX trace for diagnosis; do not invoke models or tools."""
import asyncio
from collections import Counter
from datetime import timezone, timedelta
import json
import logging
import os
from pathlib import Path
import re
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "agents"))
from dotenv import load_dotenv
load_dotenv(ROOT / "agents/.env", override=True)
logging.getLogger("langsmith").setLevel(logging.CRITICAL)
from langsmith import Client

ANALYSIS_ID = sys.argv[1] if len(sys.argv) > 1 else "96dadeb2"
PROJECT_ID = "6255651c-f7a1-444d-b783-dea7019f0664"
FIELDS = ["ID", "NAME", "START_TIME", "END_TIME", "LATENCY_SECONDS", "RUN_TYPE",
          "PARENT_RUN_IDS", "TRACE_ID", "DOTTED_ORDER", "ERROR", "EXTRA", "METADATA", "INPUTS", "OUTPUTS",
          "TOTAL_TOKENS", "PROMPT_TOKENS", "COMPLETION_TOKENS"]


def meta(run):
    return run.get("metadata") or (run.get("extra") or {}).get("metadata") or {}


def safe(value):
    encoded = json.dumps(value, ensure_ascii=False, default=str)
    for key in ("LANGSMITH_API_KEY", "OPENAI_COMPATIBLE_API_KEY"):
        secret = os.getenv(key)
        if secret:
            encoded = encoded.replace(secret, "[REDACTED]")
    return re.sub(r"lsv2_[A-Za-z0-9_]+", "[REDACTED]", encoded)


async def main():
    client = Client(timeout_ms=10000)
    roots = [r.model_dump(mode="json") async for r in client.runs.query_v2(
        project_ids=[PROJECT_ID], is_root=True, page_size=30, selects=FIELDS,
    )]
    candidates = [r for r in roots if meta(r).get("analysis_id") == ANALYSIS_ID]
    if not candidates:
        print(safe({"found": False, "roots": [{"name": r.get("name"), "meta": meta(r)} for r in roots]}))
        return
    target = max(candidates, key=lambda r: r["start_time"])
    runs = [r.model_dump(mode="json") async for r in client.runs.query_v2(
        project_ids=[PROJECT_ID], trace_id=target["id"], page_size=1000, selects=FIELDS,
    )]
    runs.sort(key=lambda r: r["start_time"])
    output = ROOT / f"logs/langsmith-analysis-{ANALYSIS_ID}.json"
    output.write_text(safe({"root": target, "runs": runs}), encoding="utf-8")
    print(safe({"root_id": target["id"], "root_error": target.get("error"), "runs": len(runs),
                "counts": dict(Counter(r["run_type"] for r in runs)), "saved": str(output)}))
    for run in runs:
        if run["run_type"] == "llm" or run["name"].startswith(("finex.", "mcp.")) or run.get("error"):
            print(safe({k: v for k, v in {
                "id": run["id"], "name": run["name"], "type": run["run_type"],
                "start": run["start_time"], "end": run.get("end_time"),
                "latency": run.get("latency_seconds"), "parents": run.get("parent_run_ids"),
                "agent": meta(run).get("agent"), "tool": meta(run).get("tool"),
                "prompt_tokens": run.get("prompt_tokens"), "completion_tokens": run.get("completion_tokens"),
                "error": (run.get("error") or "")[:1200],
                "inputs": run.get("inputs") if run["run_type"] == "tool" and not run["name"].startswith("mcp.") else None,
            }.items() if v is not None}))
    client.close(timeout=2)


if __name__ == "__main__":
    try:
        asyncio.run(main())
    except Exception as error:
        print(safe({"error_type": type(error).__name__, "detail": str(error)[:1600]}))
        sys.exit(1)
