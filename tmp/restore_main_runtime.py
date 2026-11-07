"""Restore the current local analysis sessions after moving back to the main checkout."""
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from backend.server import AnalysisStatus, analysis_sessions, app
import uvicorn

snapshot = Path(sys.argv[1]) if len(sys.argv) > 1 else ROOT / "logs" / "main-runtime-migration" / "sessions.json"
for record in json.loads(snapshot.read_text(encoding="utf-8")):
    session = AnalysisStatus.model_validate(record)
    analysis_sessions[session.analysis_id] = session

if __name__ == "__main__":
    uvicorn.run(app, host="0.0.0.0", port=8100)
