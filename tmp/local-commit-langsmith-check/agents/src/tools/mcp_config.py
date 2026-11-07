"""
MCP服务器配置模块 - 包含连接A股MCP服务器的配置信息
"""

import os
from pathlib import Path

# 自动检测项目根目录下的mcp-server路径
PROJECT_ROOT = Path(__file__).parent.parent.parent.parent
MCP_SERVER_PATH = PROJECT_ROOT / "mcp-server"

SERVER_CONFIGS = {
    "a_share_mcp_v2": {
        "command": "uv",
        "args": [
            "run",
            "--directory",
            str(MCP_SERVER_PATH),
            "python",
            "mcp_server.py"
        ],
        "transport": "stdio",
    }
}