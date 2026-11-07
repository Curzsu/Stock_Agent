import asyncio
import threading
import unittest


class ThreadedToolTests(unittest.IsolatedAsyncioTestCase):
    async def test_synchronous_data_tool_does_not_block_protocol_loop(self):
        from src.threaded_mcp import ThreadedFastMCP
        app = ThreadedFastMCP('offline')
        started = threading.Event()
        release = threading.Event()

        @app.tool()
        def slow(value: int) -> str:
            """A blocking data-source probe."""
            started.set()
            release.wait(timeout=.5)
            return str(value)

        call = asyncio.create_task(app.call_tool('slow', {'value': 7}))
        try:
            await asyncio.wait_for(asyncio.to_thread(started.wait), .2)
            self.assertFalse(call.done(), 'RPC loop must respond while data work is blocked')
            release.set()
            result = await call
            self.assertIn('7', str(result))
        finally:
            release.set()
            await call


if __name__ == '__main__':
    unittest.main()
