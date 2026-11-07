"""Snapshot terminal Web sessions before the LangSmith runtime restart."""
from datetime import datetime
import json
from pathlib import Path
import urllib.request
import sys

ROOT = Path(__file__).resolve().parents[1]
opener = urllib.request.build_opener(urllib.request.ProxyHandler({}))


def get(path):
    return json.load(opener.open("http://127.0.0.1:8100" + path, timeout=10))


records = []
for entry in get("/api/history")["history"]:
    record = get("/api/status/" + entry["analysis_id"])
    assert record["status"] in {"completed", "degraded", "error"}, "Do not interrupt active research"
    record["partial_results"] = get("/api/analysis/" + entry["analysis_id"] + "/partial")["results"]
    if record["status"] in {"completed", "degraded"}:
        record["result"] = get("/api/result/" + entry["analysis_id"])
    result = record.get("result") or {}
    record["query"] = result.get("query") or record["company_name"]
    stamp = datetime.fromisoformat(record["start_time"])
    code = result.get("stock_code") or record.get("stock_code") or entry["stock_code"]
    if "." not in code:
        code = ("sh." if code.startswith("6") else "sz.") + code
    initial = {
        "query": record["query"], "company_name": record["company_name"], "stock_code": code,
        "current_date": stamp.strftime("%Y-%m-%d"), "current_date_cn": stamp.strftime("%Y年%m月%d日"),
        "current_time": stamp.strftime("%H:%M:%S"),
        "current_weekday_cn": ["星期一", "星期二", "星期三", "星期四", "星期五", "星期六", "星期日"][stamp.weekday()],
        "analysis_timestamp": stamp.isoformat(),
    }
    initial["current_time_info"] = f"{initial['current_date_cn']} ({initial['current_date']}) {initial['current_weekday_cn']} {initial['current_time']}"
    # The failed Shenhua run logged its exact initial state before synthesis.
    execution_dirs = {'acc4dd70': '20261107_004954_72a54391', '96dadeb2': '20261107_020707_abb81494'}
    if record["analysis_id"] in execution_dirs:
        source = ROOT / 'logs' / execution_dirs[record['analysis_id']] / 'agents/summary_agent_execution.json'
        data = json.loads(source.read_text(encoding="utf-8"))["output_data"]
        assert data["stock_code"] == code
        initial = {k: data[k] for k in initial if k in data}
        record["query"] = data["query"]
    record["initial_data"] = initial
    trace_file = ROOT / f"logs/langsmith-analysis-{record['analysis_id']}.json"
    if trace_file.exists():
        trace_query = json.loads(trace_file.read_text(encoding='utf-8')).get('root',{}).get('inputs',{}).get('query')
        if trace_query:
            record['query'] = initial['query'] = trace_query
    records.append(record)

snapshot = ROOT / (sys.argv[1] if len(sys.argv) > 1 else "logs/sessions-before-langsmith-20261107.json")
assert not snapshot.exists(), "Do not overwrite a previous snapshot"
snapshot.write_text(json.dumps(records, ensure_ascii=False, indent=2), encoding="utf-8")
print(json.dumps({"saved_sessions": len(records), "fragments": sum(len(r['partial_results']) for r in records),
                  "snapshot": str(snapshot)}))
