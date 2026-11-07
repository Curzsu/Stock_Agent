from pathlib import Path
import sys
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'mcp-server'))
from src.threaded_mcp import ThreadedFastMCP
app = ThreadedFastMCP('offline-reuse-probe')
calls = 0
@app.tool()
def read_snapshot(quarter: int = 3) -> str:
    """Return a real RPC invocation counter without network data."""
    global calls
    calls += 1
    return f'RPC={calls}; quarter={quarter}'
app.run(transport='stdio')
