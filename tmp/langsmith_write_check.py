"""Distinguish trace-write permission from project-read permission."""
from datetime import datetime, timezone
from pathlib import Path
import json
from uuid import uuid4
from dotenv import dotenv_values
import requests

config = dotenv_values(Path(__file__).resolve().parents[1] / "agents/.env")
results = []
for endpoint in ("https://api.smith.langchain.com", "https://eu.api.smith.langchain.com"):
    run_id = str(uuid4())
    now = datetime.now(timezone.utc).isoformat()
    payload = {"id": run_id, "name": "finex.synthetic_connection_check", "run_type": "chain",
               "session_name": "finex-dev", "start_time": now, "end_time": now,
               "inputs": {"synthetic": True, "model_api_calls": 0},
               "outputs": {"ok": True}, "extra": {"metadata": {"synthetic": True}}}
    try:
        response = requests.post(endpoint + "/runs", timeout=10, json=payload,
                                 headers={"x-api-key": config["LANGSMITH_API_KEY"]})
        results.append({"endpoint": endpoint, "status": response.status_code,
                        "run_id": run_id if response.ok else None})
        if response.ok:
            break
    except Exception as error:
        results.append({"endpoint": endpoint, "error_type": type(error).__name__})
print(json.dumps(results))
