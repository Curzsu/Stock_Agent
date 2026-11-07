"""Test MCP server with proper initialization handshake"""
import asyncio
import subprocess
import json

async def test_mcp_server():
    # Start the MCP server as a subprocess
    proc = await asyncio.create_subprocess_exec(
        "uv", "run", "--directory", r"E:\Curzsu\Finance1\mcp-server", "python", "mcp_server.py",
        stdin=asyncio.subprocess.PIPE,
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE
    )

    # Give it a moment to start
    await asyncio.sleep(2)

    # Check if stderr has any output
    try:
        stderr_data = await asyncio.wait_for(proc.stderr.read(1000), timeout=1.0)
        if stderr_data:
            print(f"Server stderr: {stderr_data.decode()}")
    except asyncio.TimeoutError:
        pass

    async def send_request(request, timeout=10.0):
        """Send a JSON-RPC request and get response"""
        request_line = json.dumps(request) + "\n"
        print(f"Sending: {json.dumps(request)[:100]}...")
        proc.stdin.write(request_line.encode())
        await proc.stdin.drain()

        response_line = await asyncio.wait_for(proc.stdout.readline(), timeout=timeout)
        response = response_line.decode().strip()
        print(f"Received: {response[:200]}...")
        return json.loads(response) if response else None

    try:
        # Step 1: Initialize the MCP connection
        print("\n=== Step 1: Initialize ===")
        init_response = await send_request({
            "jsonrpc": "2.0",
            "id": 1,
            "method": "initialize",
            "params": {
                "protocolVersion": "2024-11-05",
                "capabilities": {},
                "clientInfo": {
                    "name": "test-client",
                    "version": "1.0.0"
                }
            }
        })

        if init_response and "result" in init_response:
            print(f"Server info: {init_response['result'].get('serverInfo', {})}")
            print(f"Protocol version: {init_response['result'].get('protocolVersion')}")

            # Step 2: Send initialized notification
            print("\n=== Step 2: Send initialized notification ===")
            notification = json.dumps({"jsonrpc": "2.0", "method": "notifications/initialized"}) + "\n"
            proc.stdin.write(notification.encode())
            await proc.stdin.drain()
            print("Notification sent")

            # Step 3: List tools
            print("\n=== Step 3: List tools ===")
            tools_response = await send_request({
                "jsonrpc": "2.0",
                "id": 2,
                "method": "tools/list",
                "params": {}
            }, timeout=30.0)

            if tools_response and "result" in tools_response:
                tools = tools_response["result"].get("tools", [])
                print(f"\n✅ SUCCESS! Got {len(tools)} tools:")
                for tool in tools[:10]:
                    print(f"  - {tool.get('name')}")
                if len(tools) > 10:
                    print(f"  ... and {len(tools) - 10} more")
            else:
                print(f"ERROR: No tools in response: {tools_response}")
        else:
            print(f"ERROR: Invalid init response: {init_response}")

    except asyncio.TimeoutError:
        print("ERROR: Timeout waiting for response!")
        # Try to read any stderr
        try:
            stderr = await asyncio.wait_for(proc.stderr.read(4096), timeout=1.0)
            if stderr:
                print(f"Stderr output: {stderr.decode()}")
        except:
            pass
    except Exception as e:
        print(f"ERROR: {e}")
        import traceback
        traceback.print_exc()

    finally:
        proc.terminate()
        try:
            await asyncio.wait_for(proc.wait(), timeout=5.0)
        except:
            proc.kill()
            await proc.wait()

if __name__ == "__main__":
    asyncio.run(test_mcp_server())