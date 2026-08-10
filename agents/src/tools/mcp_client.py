"""Load LangChain MCP tools through one application-lifetime stdio session."""

import asyncio
import os
import threading

from langchain_mcp_adapters.client import MultiServerMCPClient
from langchain_mcp_adapters.tools import load_mcp_tools

from src.tools.mcp_config import SERVER_CONFIGS
from src.utils.logging_config import ERROR_ICON, SUCCESS_ICON, WAIT_ICON, setup_logger


logger = setup_logger(__name__)

_mcp_tools = None
_mcp_client_instance = None
_mcp_session_context = None
_mcp_session = None
_mcp_session_loop = None

_mcp_init_lock = None
_mcp_init_lock_loop = None
_mcp_init_lock_mutex = threading.Lock()
_mcp_close_mutex = threading.Lock()

# Baostock uses process-global login state. Calls share one session but still
# run one at a time so concurrent analysts cannot corrupt that state.
_mcp_tool_lock = None
_mcp_tool_lock_loop = None
_mcp_tool_lock_mutex = threading.Lock()
MCP_TOOL_TIMEOUT_SECONDS = float(os.getenv("MCP_TOOL_TIMEOUT_SECONDS", "45"))


def _get_mcp_tool_lock():
    global _mcp_tool_lock, _mcp_tool_lock_loop

    current_loop = asyncio.get_running_loop()
    with _mcp_tool_lock_mutex:
        if _mcp_tool_lock is None or _mcp_tool_lock_loop is not current_loop:
            _mcp_tool_lock = asyncio.Lock()
            _mcp_tool_lock_loop = current_loop
    return _mcp_tool_lock


def serialize_mcp_tools(tools, timeout_seconds=MCP_TOOL_TIMEOUT_SECONDS):
    """Return tool copies whose async calls run one at a time with a deadline."""
    protected_tools = []
    for tool in tools:
        original_coroutine = tool.coroutine

        async def guarded_coroutine(
            *args,
            _original_coroutine=original_coroutine,
            **kwargs,
        ):
            async with _get_mcp_tool_lock():
                return await asyncio.wait_for(
                    _original_coroutine(*args, **kwargs),
                    timeout=timeout_seconds,
                )

        protected_tools.append(
            tool.model_copy(update={"coroutine": guarded_coroutine})
        )
    return protected_tools


def print_tool_details(tools):
    """Log tool names and schemas for local diagnostics."""
    logger.info(f"{SUCCESS_ICON} Tool details:")
    for index, tool in enumerate(tools, 1):
        logger.info(f"  {index}. name: {tool.name}")
        logger.info(f"     description: {tool.description}")
        for attribute in ("input_schema", "parameters", "schema"):
            value = getattr(tool, attribute, None)
            if value:
                logger.info(f"     {attribute}: {value}")
        logger.info(f"     type: {type(tool)}")


def _get_init_lock(current_loop):
    global _mcp_init_lock, _mcp_init_lock_loop

    with _mcp_init_lock_mutex:
        if _mcp_init_lock is None or _mcp_init_lock_loop is not current_loop:
            logger.info(
                f"{WAIT_ICON} Creating MCP initialization lock for event loop "
                f"{id(current_loop)}"
            )
            _mcp_init_lock = asyncio.Lock()
            _mcp_init_lock_loop = current_loop
    return _mcp_init_lock


async def _close_partial_session(session_context, error):
    if session_context is None:
        return
    try:
        await session_context.__aexit__(
            type(error) if error is not None else None,
            error,
            error.__traceback__ if error is not None else None,
        )
    except Exception as close_error:
        logger.error(
            f"{ERROR_ICON} Failed to close partially initialized MCP session: "
            f"{close_error}",
            exc_info=True,
        )


async def get_mcp_tools():
    """Return tools bound to one persistent MCP session for the current loop.

    Failed or empty initialization is never cached, so a later call can retry.
    Published tools are cached only after both session entry and tool loading
    succeed.
    """
    global _mcp_client_instance, _mcp_tools
    global _mcp_session_context, _mcp_session, _mcp_session_loop

    current_loop = asyncio.get_running_loop()
    if _mcp_tools is not None:
        if _mcp_session_loop is current_loop:
            logger.info(
                f"{SUCCESS_ICON} Returning cached MCP tools "
                f"({len(_mcp_tools)} tools)."
            )
            return _mcp_tools
        logger.error(
            f"{ERROR_ICON} Cached MCP tools belong to another event loop. "
            "Close the client before reinitializing it."
        )
        return []

    async with _get_init_lock(current_loop):
        if _mcp_tools is not None:
            return _mcp_tools if _mcp_session_loop is current_loop else []

        logger.info(
            f"{WAIT_ICON} Opening persistent MCP session 'a_share_mcp_v2'..."
        )
        session_context = None
        try:
            client = MultiServerMCPClient(SERVER_CONFIGS)
            session_context = client.session("a_share_mcp_v2")
            session = await asyncio.wait_for(
                session_context.__aenter__(),
                timeout=60.0,
            )
            loaded_tools = await asyncio.wait_for(
                load_mcp_tools(session),
                timeout=60.0,
            )

            if not loaded_tools:
                logger.warning(
                    f"{ERROR_ICON} MCP server returned no tools. "
                    "The session will close and the next call may retry."
                )
                await _close_partial_session(session_context, None)
                return []

            protected_tools = serialize_mcp_tools(loaded_tools)
            _mcp_client_instance = client
            _mcp_session_context = session_context
            _mcp_session = session
            _mcp_session_loop = current_loop
            _mcp_tools = protected_tools
            logger.info(
                f"{SUCCESS_ICON} Loaded {len(_mcp_tools)} tools through the "
                "persistent MCP session."
            )
            return _mcp_tools
        except Exception as error:
            await _close_partial_session(session_context, error)
            logger.error(
                f"{ERROR_ICON} Failed to initialize MCP client or load tools: "
                f"{error}. Result not cached; the next call will retry.",
                exc_info=True,
            )
            return []


async def close_mcp_client_sessions():
    """Exit the persistent MCP context once and reset all cached state."""
    global _mcp_client_instance, _mcp_tools
    global _mcp_session_context, _mcp_session, _mcp_session_loop
    global _mcp_init_lock, _mcp_init_lock_loop
    global _mcp_tool_lock, _mcp_tool_lock_loop

    with _mcp_close_mutex:
        session_context = _mcp_session_context
        if (
            session_context is None
            and _mcp_client_instance is None
            and _mcp_tools is None
        ):
            logger.info("MCP client was not initialized, no session to close.")
            return

        # Clear the published state atomically before awaiting context shutdown.
        _mcp_client_instance = None
        _mcp_tools = None
        _mcp_session_context = None
        _mcp_session = None
        _mcp_session_loop = None
        _mcp_init_lock = None
        _mcp_init_lock_loop = None
        _mcp_tool_lock = None
        _mcp_tool_lock_loop = None

    if session_context is not None:
        try:
            await session_context.__aexit__(None, None, None)
            logger.info(f"{SUCCESS_ICON} Persistent MCP session closed.")
        except Exception as error:
            logger.error(
                f"{ERROR_ICON} Error while closing MCP session: {error}",
                exc_info=True,
            )


async def _main_test_mcp_client():
    tools = await get_mcp_tools()
    print_tool_details(tools)
    await close_mcp_client_sessions()


if __name__ == "__main__":
    asyncio.run(_main_test_mcp_client())
