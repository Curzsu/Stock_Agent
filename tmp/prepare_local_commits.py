"""Prepare reviewable commit snapshots without touching the running checkout."""
import ast
import hashlib
import json
from pathlib import Path
import re
import subprocess

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / 'tmp/local-commit-bundles'
OUT.mkdir(parents=True, exist_ok=True)
BASE = 'd0ee479095936daf7ddcccaa2bcc433ab5ebd33b'

def git(*args):
    return subprocess.check_output(['git', *args], cwd=ROOT)

def current(path):
    return (ROOT/path).read_text(encoding='utf-8')

def base(path):
    return git('show',f'{BASE}:{path}').decode('utf-8')

def put(group, path, value):
    data = value.encode('utf-8') if isinstance(value,str) else value
    if path.endswith('.py'):
        ast.parse(data.decode('utf-8'), filename=path)
    if re.search(rb'lsv2_(?:sk|pt)_[A-Za-z0-9]{20,}_[A-Za-z0-9]{5,}',data):
        raise RuntimeError('Unexpected credential in commit input: '+path)
    target=OUT/group/path
    target.parent.mkdir(parents=True,exist_ok=True)
    target.write_bytes(data)

smith_paths=['README.md','requirements.txt','agents/src/main.py','agents/src/utils/workflow_builder.py',
             'docs/langsmith.md','tests/test_observability.py']
for path in smith_paths:
    put('langsmith',path,current(path))

env=current('agents/.env.example')
start=env.index('# MCP 普通工具')
end=env.index('# PDF:',start)
put('langsmith','agents/.env.example',env[:start]+env[end:])

obs=current('agents/src/utils/observability.py')
obs=obs.replace('from src.utils.research_scope import research_scope, agent_role\n','')
obs=obs.replace('with agent_role(agent_key), trace_scope(', 'with trace_scope(')
start=obs.index('    async with research_scope():',obs.index('async def invoke_workflow'))
end=obs.index('\n\n\nasync def flush_traces',start)
block=obs[start:end].splitlines()[1:]
obs=obs[:start]+'\n'.join(line[4:] for line in block)+obs[end:]
put('langsmith','agents/src/utils/observability.py',obs)

server=current('backend/server.py').replace('from src.utils.research_scope import research_scope\n','')
start=server.index('    async with research_scope():',server.index('async def retry_agent_and_summary'))
end=server.index('\n\n\nasync def _retry_agent_and_summary',start)
server=server[:start]+'\n'.join(line[4:] for line in server[start:end].splitlines()[1:])+server[end:]
put('langsmith','backend/server.py',server)

# The tracing-only stage retains the old deadline/transport behavior.
mcp=base('agents/src/tools/mcp_client.py')
marker='from src.utils.logging_config import ERROR_ICON, SUCCESS_ICON, WAIT_ICON, setup_logger\n'
assert marker in mcp
mcp=mcp.replace(marker,marker+'from src.utils.observability import trace_scope\n')
mcp=mcp.replace('            _original_coroutine=original_coroutine,\n',
                '            _original_coroutine=original_coroutine,\n            _tool_name=tool.name,\n',1)
mcp=mcp.replace('            async with _get_mcp_tool_lock():\n',
'''            lock = _get_mcp_tool_lock()
            with trace_scope("mcp.queue", metadata={"tool": _tool_name}, run_type="tool"):
                await lock.acquire()
            try:
''',1)
old='''                    return await asyncio.wait_for(
                        _original_coroutine(*args, **kwargs),
                        timeout=timeout_seconds,
                    )'''
new='''                    with trace_scope("mcp.execute", metadata={"tool": _tool_name}, run_type="tool"):
                        return await asyncio.wait_for(
                            _original_coroutine(*args, **kwargs),
                            timeout=timeout_seconds,
                        )'''
assert old in mcp
mcp=mcp.replace(old,new,1)
marker='\n        protected_tools.append('
assert marker in mcp
mcp=mcp.replace(marker,'            finally:\n                lock.release()\n'+marker,1)
put('langsmith','agents/src/tools/mcp_client.py',mcp)

names=git('diff','--name-only','-z').decode().split('\0')
names += git('ls-files','--others','--exclude-standard','-z').decode().split('\0')
paths=sorted({p for p in names if p})
chart={'.github/workflows/ci.yml','frontend/workbench.js','tests/frontend/test_workbench_chart.cjs'}
for path in paths:
    put('chart' if path in chart else 'analysis',path,current(path))

manifest={'base':BASE,'groups':{},'working_hashes':{}}
for group in ['langsmith','analysis','chart']:
    manifest['groups'][group]=[p.relative_to(OUT/group).as_posix() for p in sorted((OUT/group).rglob('*')) if p.is_file()]
for path in paths:
    manifest['working_hashes'][path]=hashlib.sha256((ROOT/path).read_bytes()).hexdigest()
(OUT/'manifest.json').write_text(json.dumps(manifest,ensure_ascii=False,indent=2),encoding='utf-8')
print(json.dumps({g:len(p) for g,p in manifest['groups'].items()}))
