"""
MCP服务器配置模块 - 包含连接A股MCP服务器的配置信息
"""
import sys
import os

# 获取当前 Python 解释器路径
PYTHON_EXECUTABLE = sys.executable

# MCP 服务器项目路径
MCP_SERVER_PATH = r"E:\Curzsu\Finance\a-share-mcp-is-just-i-need"

SERVER_CONFIGS = {
    "a_share_mcp_v2": {  
        "command": PYTHON_EXECUTABLE,  # 使用当前 Python 环境
        "args": [
            os.path.join(MCP_SERVER_PATH, "mcp_server.py")
        ],
        "transport": "stdio",
        "env": {
            "PYTHONPATH": MCP_SERVER_PATH,
            "PYTHONIOENCODING": "utf-8"
        }
    }
}