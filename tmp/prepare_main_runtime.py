"""Preserve local reports and sessions before retiring the isolated runtime."""
import hashlib
import json
import shutil
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
OLD = ROOT / ".worktrees" / "v2-runtime"
BACKUP = ROOT / "logs" / "main-runtime-migration"
assert OLD.resolve() == Path("E:/Curzsu/Finance1/.worktrees/v2-runtime").resolve()
assert not BACKUP.exists(), "Migration backup already exists; inspect before continuing"
client = urllib.request.build_opener(urllib.request.ProxyHandler({}))

def get(path):
    return json.load(client.open("http://127.0.0.1:8100" + path, timeout=10))

def rewrite(value):
    if isinstance(value, str):
        return value.replace(str(OLD), str(ROOT)).replace(OLD.as_posix(), ROOT.as_posix())
    if isinstance(value, list):
        return [rewrite(item) for item in value]
    if isinstance(value, dict):
        return {key: rewrite(item) for key, item in value.items()}
    return value

records = []
for entry in get("/api/history")["history"]:
    record = get("/api/status/" + entry["analysis_id"])
    assert record["status"] in {"error", "completed", "degraded"}, "Active analysis must finish before restart"
    record["partial_results"] = get("/api/analysis/" + entry["analysis_id"] + "/partial")["results"]
    if record["status"] in {"completed", "degraded"}:
        record["result"] = get("/api/result/" + entry["analysis_id"])
    records.append(rewrite(record))

BACKUP.mkdir(parents=True)
(BACKUP / "sessions-original.json").write_text(json.dumps(records, ensure_ascii=False), encoding="utf-8")
(BACKUP / "sessions.json").write_text(json.dumps(records, ensure_ascii=False), encoding="utf-8")
for relative in ("agents/reports", "logs", ".runtime"):
    source = OLD / relative
    if source.exists():
        shutil.copytree(source, BACKUP / "worktree-data" / relative)

for source in (OLD / "agents/reports").rglob("*"):
    if not source.is_file():
        continue
    destination = ROOT / source.relative_to(OLD)
    if destination.exists():
        assert hashlib.sha256(source.read_bytes()).digest() == hashlib.sha256(destination.read_bytes()).digest(), str(destination)
    else:
        destination.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(source, destination)

old_config = OLD / "agents/.env"
main_config = ROOT / "agents/.env"
if old_config.exists():
    shutil.copy2(old_config, BACKUP / "runtime.env.backup")
    if main_config.exists():
        shutil.copy2(main_config, BACKUP / "main.env.backup")
    if not main_config.exists() or old_config.read_bytes() != main_config.read_bytes():
        shutil.copy2(old_config, main_config)

print("Preserved sessions:", len(records))
print("Backup:", BACKUP)
