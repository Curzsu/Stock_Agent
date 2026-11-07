"""Keep the MCP protocol loop responsive during synchronous data I/O."""
import asyncio
from functools import wraps
import inspect

from mcp.server.fastmcp import FastMCP


class ThreadedFastMCP(FastMCP):
    def tool(self, *args, **kwargs):
        register = super().tool(*args, **kwargs)

        def decorate(function):
            if inspect.iscoroutinefunction(function):
                return register(function)

            @wraps(function)
            async def offloaded(*values, **named):
                return await asyncio.to_thread(function, *values, **named)

            return register(offloaded)

        return decorate
