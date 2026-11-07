"""Compatibility exports for the shared Web/MCP BaoStock runtime."""
import sys
from pathlib import Path

_root = str(Path(__file__).resolve().parents[3])
if _root not in sys.path:
    sys.path.append(_root)

from finex_data.baostock_runtime import (  # noqa: E402,F401
    BaostockBlacklistedError,
    BaostockDataError,
    ensure_logged_in,
    safe_query,
    shutdown,
)
