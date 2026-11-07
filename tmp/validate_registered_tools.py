import asyncio
import json
import os
from pathlib import Path
import sys
os.environ['LANGSMITH_TRACING'] = 'false'
ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'agents'))
from src.tools import mcp_client

async def main():
    mcp_client.SERVER_CONFIGS = {'a_share_mcp_v2': {
        'command': str(ROOT / 'mcp-server/.venv/Scripts/python.exe'),
        'args': [str(ROOT / 'mcp-server/mcp_server.py')], 'transport': 'stdio',
    }}
    try:
        tools = await mcp_client.get_mcp_tools()
        names = {t.name for t in tools}
        assert {'get_stock_analysis', 'crawl_news', 'get_stock_basic_info'} <= names
        print(json.dumps({'registered_tools': len(names), 'schema_load_ok': True}))
    finally:
        await mcp_client.close_mcp_client_sessions()

asyncio.run(main())
