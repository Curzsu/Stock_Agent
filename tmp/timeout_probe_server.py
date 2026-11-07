import os
from pathlib import Path
import sys
import time
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'mcp-server'))
from src.threaded_mcp import ThreadedFastMCP
app = ThreadedFastMCP('timeout-offline-probe')

@app.tool()
def probe(hang: bool = False) -> str:
    """An offline process-lifecycle probe, never accesses network data."""
    if hang:
        time.sleep(30)
    return str(os.getpid())

app.run(transport='stdio')
