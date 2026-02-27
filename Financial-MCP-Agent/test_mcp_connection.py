"""
MCP 连接测试脚本
"""
import asyncio
import sys
import os

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from src.tools.mcp_client import get_mcp_tools, close_mcp_client_sessions


async def test_mcp_connection():
    """测试 MCP 客户端是否能正常连接到服务器并获取工具"""
    print("=" * 60)
    print("MCP 连接测试")
    print("=" * 60)
    
    print("\n[1] 正在尝试连接 MCP 服务器...")
    print("    配置信息:")
    print("    - 服务器名称: a_share_mcp_v2")
    print("    - 启动命令: uv run --directory E:\\Curzsu\\Finance\\a-share-mcp-is-just-i-need python mcp_server.py")
    print("    - 传输协议: stdio")
    
    try:
        tools = await get_mcp_tools()
        
        if tools:
            print(f"\n[✓] 成功加载 {len(tools)} 个工具:\n")
            for i, tool in enumerate(tools, 1):
                print(f"    {i:2d}. {tool.name}")
                if hasattr(tool, 'description') and tool.description:
                    desc = tool.description[:100] + "..." if len(tool.description) > 100 else tool.description
                    print(f"        描述: {desc}")
            print("\n" + "=" * 60)
            print("[✓] MCP 连接测试成功!")
            print("=" * 60)
            return True
        else:
            print("\n[✗] 加载工具失败: 返回的工具列表为空")
            print("\n可能的原因:")
            print("    1. 'uv' 命令未安装或不在 PATH 中")
            print("    2. MCP 服务器路径不正确")
            print("    3. Python 环境问题")
            print("    4. MCP 服务器启动失败")
            
            print("\n建议检查:")
            print("    - 运行 'uv --version' 检查 uv 是否安装")
            print("    - 手动启动 MCP 服务器验证:")
            print("      cd E:\\Curzsu\\Finance\\a-share-mcp-is-just-i-need && python mcp_server.py")
            
            await close_mcp_client_sessions()
            return False
            
    except Exception as e:
        print(f"\n[✗] MCP 连接失败: {type(e).__name__}: {e}")
        print("\n详细错误信息:")
        import traceback
        traceback.print_exc()
        
        print("\n建议检查:")
        print("    1. 确认 'uv' 已安装: uv --version")
        print("    2. 确认 MCP 服务器路径存在")
        print("    3. 确认 Python 环境正确")
        
        await close_mcp_client_sessions()
        return False


async def test_tool_call():
    """测试调用一个简单的工具"""
    print("\n" + "=" * 60)
    print("工具调用测试")
    print("=" * 60)
    
    try:
        tools = await get_mcp_tools()
        
        if not tools:
            print("[✗] 无法获取工具，跳过工具调用测试")
            return False
        
        # 查找获取股票基本信息的工具
        target_tool = None
        for tool in tools:
            if 'stock_basic' in tool.name.lower() or 'basic_info' in tool.name.lower():
                target_tool = tool
                break
        
        if not target_tool:
            print("[!] 未找到合适的测试工具，使用第一个工具进行测试")
            target_tool = tools[0]
        
        print(f"\n[2] 尝试调用工具: {target_tool.name}")
        print(f"    工具描述: {target_tool.description[:100]}...")
        
        # 尝试调用工具
        print("\n    注意: 实际工具调用需要在 Agent 环境中进行")
        print("    此测试仅验证工具加载成功")
        
        await close_mcp_client_sessions()
        return True
        
    except Exception as e:
        print(f"[✗] 工具调用测试失败: {e}")
        await close_mcp_client_sessions()
        return False


async def check_uv_installed():
    """检查 uv 是否安装"""
    print("\n[0] 检查 'uv' 命令...")
    import subprocess
    try:
        result = subprocess.run(['uv', '--version'], capture_output=True, text=True, timeout=5)
        if result.returncode == 0:
            print(f"    [✓] uv 已安装: {result.stdout.strip()}")
            return True
        else:
            print(f"    [✗] uv 返回错误: {result.stderr}")
            return False
    except FileNotFoundError:
        print("    [✗] uv 未安装或不在 PATH 中")
        print("    安装方法: pip install uv 或 pipx install uv")
        return False
    except Exception as e:
        print(f"    [✗] 检查 uv 时出错: {e}")
        return False


async def main():
    print("\n" + "=" * 60)
    print("Financial-MCP-Agent MCP 连接诊断")
    print("=" * 60)
    
    # 检查 uv
    uv_ok = await check_uv_installed()
    
    if not uv_ok:
        print("\n" + "=" * 60)
        print("[!] 警告: 'uv' 未正确安装")
        print("=" * 60)
        print("\n需要安装 'uv' 才能启动 MCP 服务器。")
        print("安装方法:")
        print("    pip install uv")
        print("\n或者，您可以修改 mcp_config.py 使用直接 Python 命令:")
        print("    将 'command': 'uv' 改为 'command': 'python'")
        print("    将 'args' 简化为 ['mcp_server.py']")
        return
    
    # 测试 MCP 连接
    connection_ok = await test_mcp_connection()
    
    if connection_ok:
        # 测试工具调用
        await test_tool_call()
    
    print("\n" + "=" * 60)
    print("诊断完成")
    print("=" * 60)


if __name__ == "__main__":
    asyncio.run(main())