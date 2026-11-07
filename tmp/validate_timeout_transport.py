import asyncio
import json
import os
from pathlib import Path
import sys
import time
os.environ['LANGSMITH_TRACING'] = 'false'
ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'agents'))
from src.tools import mcp_client

async def main():
    mcp_client.MCP_TOOL_TIMEOUT_SECONDS = .2
    mcp_client.SERVER_CONFIGS = {'a_share_mcp_v2': {
        'command': str(ROOT / 'mcp-server/.venv/Scripts/python.exe'),
        'args': [str(ROOT / 'tmp/timeout_probe_server.py')], 'transport': 'stdio',
    }}
    try:
        tools = await mcp_client.get_mcp_tools()
        assert tools, 'initial load'
        owner = mcp_client._mcp_session_task
        started = time.monotonic()
        failed, recovered = await asyncio.gather(tools[0].ainvoke({'hang': True}), tools[0].ainvoke({'hang': False}))
        assert '超时' in failed, failed
        assert '超时' not in str(recovered), recovered
        assert owner.done(), 'old owner still running'
        assert mcp_client._mcp_session_task is not owner, 'stale session reused'
        print(json.dumps({'recovered': True, 'old_owner_closed': owner.done(),
                          'elapsed': round(time.monotonic()-started, 2), 'result': str(recovered)}))
    finally:
        await mcp_client.close_mcp_client_sessions()

asyncio.run(main())
