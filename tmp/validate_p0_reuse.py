import asyncio
import json
import os
from pathlib import Path
import sys
os.environ['LANGSMITH_TRACING']='false'
ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT/'agents'))
from src.tools import mcp_client
from src.utils.research_scope import research_scope
async def main():
    mcp_client.SERVER_CONFIGS={'a_share_mcp_v2':{'command':str(ROOT/'mcp-server/.venv/Scripts/python.exe'),
        'args':[str(ROOT/'tmp/p0_reuse_probe_server.py')], 'transport':'stdio'}}
    try:
        tools=await mcp_client.get_mcp_tools()
        assert tools
        tool=tools[0]
        async with research_scope():
            results=await asyncio.gather(*(tool.ainvoke({} if i%2 else {'quarter':3}) for i in range(10)))
            assert all('RPC=1;' in str(r) for r in results),str(results)
            assert 'RPC=1;' in str(await tool.ainvoke({'quarter':3}))
        async with research_scope():
            assert 'RPC=2;' in str(await tool.ainvoke({'quarter':3}))
        print(json.dumps({'parallel_requests':10,'actual_rpc_calls':1,'later_cache_hit':True,'next_analysis_refetched':True}))
    finally:
        await mcp_client.close_mcp_client_sessions()
asyncio.run(main())
