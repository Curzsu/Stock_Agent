import json
from collections import Counter
from pathlib import Path

d = json.loads(Path('logs/langsmith-analysis-f1fe9840.json').read_text(encoding='utf-8'))
runs = d['runs']
def meta(r):
    return r.get('metadata') or (r.get('extra') or {}).get('metadata') or {}

for name in ['get_growth_data','get_operation_data','get_balance_data','get_cash_flow_data','get_dupont_data']:
    candidates = [r for r in runs if r['name']==name and r.get('latency_seconds')]
    if not candidates:
        continue
    r = min(candidates, key=lambda r:r['start_time'])
    phases = [p for p in runs if p['name'] in ('mcp.queue','mcp.execute')
              and meta(p).get('agent')==meta(r).get('agent') and meta(p).get('tool')==name
              and r['start_time'] <= p['start_time'] <= r['end_time']]
    print(json.dumps({'tool':name,'role':meta(r).get('agent'),'total':round(r['latency_seconds'],2),
                      'phases':[(p['name'],round(p.get('latency_seconds') or 0,2)) for p in phases]}))

tools = [r for r in runs if r['run_type']=='tool' and not r['name'].startswith('mcp.')]
counts = Counter((r['name'],json.dumps(r.get('inputs'),sort_keys=True)) for r in tools)
print('TOOLS',len(tools),'DUPLICATE_REQUESTS',sum(v-1 for v in counts.values()))
print('REPEATS',[(k,v) for k,v in counts.items() if v>1])
print('MODELS',[(meta(r).get('agent'),round(r.get('latency_seconds') or 0,2),r.get('prompt_tokens'),r.get('completion_tokens')) for r in runs if r['run_type']=='llm'])
print('ROOT',d['root']['id'],d['root']['start_time'],d['root'].get('end_time'))
