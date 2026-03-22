"""Test langchain-mcp-adapters directly to diagnose hang issue"""
import asyncio
import sys
from pathlib import Path

# Add agents to path
project_root = Path(__file__).parent
sys.path.insert(0, str(project_root / "agents"))

from langchain_mcp_adapters.client import MultiServerMCPClient
from langchain_mcp_adapters.sessions import create_session

# MCP server path
MCP_SERVER_PATH = project_root / "mcp-server"

SERVER_CONFIG = {
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

async def test_langchain_mcp_adapter():
    """Test the langchain-mcp-adapters library directly"""

    print("=" * 60)
    print("Test 1: Using MultiServerMCPClient.get_tools()")
    print("=" * 60)

    try:
        print("Creating MultiServerMCPClient...")
        client = MultiServerMCPClient(SERVER_CONFIG)

        print("Calling get_tools()...")
        # Set a timeout to see if it hangs
        tools = await asyncio.wait_for(client.get_tools(), timeout=30.0)

        print(f"SUCCESS! Got {len(tools)} tools:")
        for i, tool in enumerate(tools[:5], 1):
            print(f"  {i}. {tool.name}")
        if len(tools) > 5:
            print(f"  ... and {len(tools) - 5} more")

    except asyncio.TimeoutError:
        print("ERROR: get_tools() TIMED OUT after 30 seconds!")
    except Exception as e:
        print(f"ERROR: {e}")
        import traceback
        traceback.print_exc()


async def test_create_session_directly():
    """Test create_session directly to isolate the issue"""

    print("\n" + "=" * 60)
    print("Test 2: Using create_session directly")
    print("=" * 60)

    connection = SERVER_CONFIG["a_share_mcp_v2"]

    try:
        print("Creating session...")
        async with asyncio.timeout(30.0):
            async with create_session(connection) as session:
                print("Session created, calling initialize()...")
                await asyncio.wait_for(session.initialize(), timeout=15.0)
                print("Session initialized!")

                print("Calling list_tools()...")
                result = await asyncio.wait_for(session.list_tools(), timeout=15.0)
                print(f"SUCCESS! Got {len(result.tools)} tools:")
                for i, tool in enumerate(result.tools[:5], 1):
                    print(f"  {i}. {tool.name}")

    except asyncio.TimeoutError:
        print("ERROR: TIMED OUT!")
    except Exception as e:
        print(f"ERROR: {e}")
        import traceback
        traceback.print_exc()


async def test_mcp_client_stdlib_directly():
    """Test mcp.client.stdio directly (bypassing langchain-mcp-adapters)"""

    print("\n" + "=" * 60)
    print("Test 3: Using mcp.client.stdio directly")
    print("=" * 60)

    from mcp import ClientSession, StdioServerParameters
    from mcp.client.stdio import stdio_client
    import os

    # Set up environment with PATH
    env = {"PATH": os.environ.get("PATH", "")}

    server_params = StdioServerParameters(
        command="uv",
        args=[
            "run",
            "--directory",
            str(MCP_SERVER_PATH),
            "python",
            "mcp_server.py"
        ],
        env=env,
    )

    try:
        print("Starting stdio_client...")
        async with asyncio.timeout(60.0):
            async with stdio_client(server_params) as (read, write):
                print("stdio_client started, creating ClientSession...")
                async with ClientSession(read, write) as session:
                    print("ClientSession created, calling initialize()...")
                    await asyncio.wait_for(session.initialize(), timeout=15.0)
                    print("Session initialized!")

                    print("Calling list_tools()...")
                    result = await asyncio.wait_for(session.list_tools(), timeout=15.0)
                    print(f"SUCCESS! Got {len(result.tools)} tools:")
                    for i, tool in enumerate(result.tools[:5], 1):
                        print(f"  {i}. {tool.name}")

    except asyncio.TimeoutError:
        print("ERROR: TIMED OUT!")
    except Exception as e:
        print(f"ERROR: {e}")
        import traceback
        traceback.print_exc()


if __name__ == "__main__":
    print("Testing langchain-mcp-adapters library")
    print("=" * 60)

    # Run tests in order
    asyncio.run(test_mcp_client_stdlib_directly())
    asyncio.run(test_create_session_directly())
    asyncio.run(test_langchain_mcp_adapter())