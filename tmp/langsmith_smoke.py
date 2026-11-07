"""Local integration acceptance: two synthetic spans, no model API calls."""
import asyncio
import json
import logging
import os
import re
from pathlib import Path
import sys
import time
from uuid import uuid4

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "agents"))
from dotenv import load_dotenv
load_dotenv(ROOT / "agents/.env", override=True)
logging.getLogger("langsmith").setLevel(logging.CRITICAL)

from src.utils.observability import analysis_trace, get_client, trace_scope


def main():
    client = get_client()
    project = next(client.list_projects(name="finex-dev", limit=1), None)
    if project is None:
        project = client.create_project("finex-dev", description="FINEX development tracing", upsert=True)
    state = {"data": {"query": "Synthetic integration check; no model call"},
             "metadata": {"analysis_id": f"smoke-{uuid4()}"}}
    with analysis_trace(state, operation="smoke") as root:
        if root is None:
            raise RuntimeError("Tracing was not enabled")
        with trace_scope("finex.synthetic_probe", metadata={"synthetic": True}) as child:
            child.end(outputs={"ok": True, "model_api_calls": 0})
        root.end(outputs={"ok": True, "synthetic": True, "model_api_calls": 0})
    client.flush(timeout=5)

    async def retrieve(run):
        return await client.runs.retrieve_v2(
            str(run.id), project_id=str(project.id), start_time=run.start_time,
            selects=["ID", "NAME", "PARENT_RUN_IDS", "TRACE_ID", "ERROR", "END_TIME"],
        )

    for attempt in range(6):
        try:
            saved_root = asyncio.run(retrieve(root))
            saved_child = asyncio.run(retrieve(child))
            break
        except Exception:
            if attempt == 5:
                raise
            time.sleep(2)
    result = {"ok": True, "project": project.name, "project_id": str(project.id),
              "root_id": str(root.id), "child_id": str(child.id),
              "root_name": saved_root.name, "child_name": saved_child.name,
              "url": f"https://smith.langchain.com/o/{project.tenant_id}/projects/p/{project.id}",
              "model_api_calls": 0}
    (ROOT / "logs/langsmith-smoke.json").write_text(json.dumps(result, indent=2), encoding="utf-8")
    print(json.dumps(result))
    client.close(timeout=5)


if __name__ == "__main__":
    try:
        main()
    except Exception as error:
        safe = str(error).replace(os.getenv("LANGSMITH_API_KEY", "not-set"), "[REDACTED]")
        safe = re.sub(r"lsv2_[A-Za-z0-9_]+", "[REDACTED]", safe)
        print(json.dumps({"ok": False, "error_type": type(error).__name__, "detail": safe[:1600]}))
        sys.exit(1)
