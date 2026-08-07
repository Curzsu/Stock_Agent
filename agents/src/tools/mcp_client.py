"""
MCP 客户端模块 —— 加载并缓存 MCP 服务器提供的 LangChain 兼容工具。

设计要点（基于 langchain-mcp-adapters 源码验证后的结论）：

1. `MultiServerMCPClient` 本身是无状态的：它只保存 connections 配置，
   不持有任何活跃 session。`get_tools()` 只是临时开一个 session 列出工具
   并立即关闭。

2. 返回的 `StructuredTool` 对象内部闭包捕获的是 `connection` 配置，
   不是活跃 session。每次工具被真正调用时，`call_tool` 会
   `async with create_session(connection)` 现场启动一个全新的 stdio
   子进程 -> 握手 -> 调用 -> 关闭子进程。

   因此工具调用天然是相互隔离的，不存在「并发请求复用同一 stdio 管道
   导致响应串台」的问题。

3. 本模块缓存的是「工具列表（tool 对象）」而非「活跃连接」。工具对象
   每次被调用都会自己开新子进程，所以缓存它们是安全的、进程级长驻即可。

历史 bug 修复：
- 失败时不再缓存空列表 `_mcp_tools = []`，否则一次超时会让整个进程
  永久瘫痪（fast path `if _mcp_tools is not None` 会一直返回空列表），
  必须重启才能恢复。现在失败时返回 `[]` 但不写缓存，下次调用会重试。
- `close_mcp_client_sessions()` 现在用锁保护、原子地清空全部全局状态，
  避免并发下部分清空导致的状态不一致。它只在应用关停时调用，
  不应在每次请求结束时调用（那样会让每个请求都重新加载工具列表）。
"""
from langchain_mcp_adapters.client import MultiServerMCPClient
from src.utils.logging_config import setup_logger, SUCCESS_ICON, ERROR_ICON, WAIT_ICON
from src.tools.mcp_config import SERVER_CONFIGS
import asyncio
import threading

logger = setup_logger(__name__)

# ============================================================================
# 进程级缓存状态
# ============================================================================
# 缓存的工具列表。None 表示尚未加载；list 表示已加载（包括空列表，但空列表
# 只在「服务器确实没有工具」时才缓存，加载失败绝不缓存，见下方逻辑）。
_mcp_tools = None
# MultiServerMCPClient 引用。该 client 无状态，保留引用仅为 close 时清理。
_mcp_client_instance = None
# 保护初始化的 asyncio 锁。按事件循环隔离（一个循环一把锁）。
_mcp_init_lock = None
_mcp_init_lock_loop = None
# 保护「锁创建」本身的线程锁，确保每个事件循环只创建一把 asyncio.Lock。
_mcp_init_lock_mutex = threading.Lock()
# 保护「关闭」过程的线程锁，避免 close 与 get_mcp_tools 并发交错。
_mcp_close_mutex = threading.Lock()


def print_tool_details(tools):
    """打印工具的详细信息，用于调试"""
    logger.info(f"{SUCCESS_ICON} 工具详细信息:")
    for i, tool in enumerate(tools, 1):
        logger.info(f"  {i}. 工具名称: {tool.name}")
        logger.info(f"     描述: {tool.description}")

        # 打印其他可能的属性
        for attr in ['input_schema', 'parameters', 'schema']:
            if hasattr(tool, attr):
                attr_value = getattr(tool, attr)
                if attr_value:
                    logger.info(f"     {attr}: {attr_value}")

        logger.info(f"     工具类型: {type(tool)}")
        logger.info("     " + "-" * 50)


async def get_mcp_tools():
    """
    获取 MCP 服务器提供的 LangChain 兼容工具列表，带进程级缓存。

    缓存策略：
    - 首次调用时加载工具列表并缓存，后续调用直接返回缓存。
    - 加载失败时不缓存结果（返回空列表但不写入缓存），保证下次调用会重试，
      避免「一次超时 -> 进程永久瘫痪」的故障模式。
    - 服务器确实返回空工具列表时（正常情况但无可控工具），按空列表缓存，
      避免反复无意义地尝试。

    Returns:
        list: 从 MCP 服务器加载的 LangChain 兼容工具列表。
              如果初始化或工具加载失败，返回空列表。
    """
    global _mcp_client_instance, _mcp_tools, _mcp_init_lock, _mcp_init_lock_loop

    # Fast path: 已缓存则直接返回（持有缓存期间不持锁，工具调用各自开子进程）
    if _mcp_tools is not None:
        logger.info(f"{SUCCESS_ICON} Returning cached MCP tools ({len(_mcp_tools)} tools).")
        return _mcp_tools

    # 获取当前事件循环，按循环创建 asyncio.Lock
    current_loop = asyncio.get_running_loop()

    with _mcp_init_lock_mutex:
        if _mcp_init_lock is None or _mcp_init_lock_loop is not current_loop:
            logger.info(f"{WAIT_ICON} Creating new async lock for event loop {id(current_loop)}")
            _mcp_init_lock = asyncio.Lock()
            _mcp_init_lock_loop = current_loop

    async with _mcp_init_lock:
        # 双重检查：持锁后再次确认（可能已被其他协程初始化）
        if _mcp_tools is not None:
            logger.info(f"{SUCCESS_ICON} Returning MCP tools (initialized by another coroutine).")
            return _mcp_tools

        logger.info(
            f"{WAIT_ICON} Initializing MultiServerMCPClient with config: {SERVER_CONFIGS}")
        try:
            client = MultiServerMCPClient(SERVER_CONFIGS)

            logger.info(
                f"{WAIT_ICON} Fetching tools from MCP server 'a_share_mcp_v2'...")
            # get_tools() 会临时开一个 stdio session 列出工具后立即关闭
            try:
                loaded_tools = await asyncio.wait_for(
                    client.get_tools(),
                    timeout=60.0
                )
            except asyncio.TimeoutError:
                # 关键修复：超时不缓存，下次调用可重试
                logger.error(
                    f"{ERROR_ICON} Timeout (60s) waiting for MCP server to respond. "
                    f"The server may be stuck or not starting. Result NOT cached — next call will retry.")
                return []

            if not loaded_tools:
                # 服务器连通但没有工具：这是「确定的无工具」状态，可以缓存空列表
                # 以避免反复尝试；但仍记录警告便于排查配置问题。
                logger.warning(
                    f"{ERROR_ICON} No tools loaded from MCP server 'a_share_mcp_v2'. "
                    f"Check server logs and configuration. Caching empty list.")
                _mcp_tools = []
                _mcp_client_instance = client
                return []

            # 成功加载：缓存工具列表与 client 引用
            _mcp_tools = loaded_tools
            _mcp_client_instance = client
            logger.info(
                f"{SUCCESS_ICON} Successfully loaded {len(_mcp_tools)} tools from 'a_share_mcp_v2'.")

            return _mcp_tools

        except Exception as e:
            # 关键修复：异常不缓存，下次调用可重试
            logger.error(
                f"{ERROR_ICON} Failed to initialize MCP client or load tools: {e}. "
                f"Result NOT cached — next call will retry.", exc_info=True)
            return []


async def close_mcp_client_sessions():
    """
    关闭并清理 MCP 客户端缓存的全部状态。

    重要：本函数应只在应用关停时调用（例如 FastAPI 的 shutdown 事件），
    不应在每次分析请求结束时调用。原因：
    - 工具列表是进程级缓存，清掉后下一个请求要重新启动 MCP 子进程、
      握手、列出工具，带来数秒无谓开销。
    - 工具对象每次调用都自己开新子进程，不持有长驻连接，所以请求级
      清理既无隔离收益，又损失缓存命中率。

    本函数用线程锁保护，保证「清空 client 引用 + 清空工具缓存 + 重置锁」
    是原子操作，避免与 `get_mcp_tools` 并发时出现部分清空的不一致状态。
    """
    global _mcp_client_instance, _mcp_tools, _mcp_init_lock, _mcp_init_lock_loop

    with _mcp_close_mutex:
        if _mcp_client_instance is None and _mcp_tools is None:
            logger.info("MCP client was not initialized, no sessions to close.")
            return

        logger.info(f"{WAIT_ICON} Closing MCP client sessions...")
        # MultiServerMCPClient 不持有活跃 session（工具调用各自管理子进程），
        # 但若该版本提供了 close 方法，仍调用以释放可能持有的资源。
        if _mcp_client_instance is not None:
            try:
                if hasattr(_mcp_client_instance, 'close'):
                    await _mcp_client_instance.close()
                logger.info(
                    f"{SUCCESS_ICON} MCP client sessions closed successfully.")
            except Exception as e:
                logger.error(
                    f"{ERROR_ICON} Error during MCP client session cleanup: {e}", exc_info=True)

        # 原子地清空全部全局状态，允许后续重新初始化
        _mcp_client_instance = None
        _mcp_tools = None
        _mcp_init_lock = None
        _mcp_init_lock_loop = None


# 测试此模块的示例（可选，用于直接执行）
async def _main_test_mcp_client():
    logger.info("--- Testing MCP Client Tool Loading ---")
    tools = await get_mcp_tools()
    if tools:
        print(f"Successfully loaded {len(tools)} tools:")
        for tool in tools:
            print(
                f"- Name: {tool.name}")

        # 测试一个简单的工具调用（如果有合适的工具）
        if tools:
            logger.info("--- Testing Tool Call ---")
            # 尝试调用第一个工具（需要根据实际工具调整参数）
            first_tool = tools[0]
            logger.info(f"尝试调用工具: {first_tool.name}")

            # 这里需要根据实际的工具参数schema来构造测试参数
            # 暂时跳过实际调用，只是展示结构
            logger.info("工具调用测试跳过（需要实际参数）")
    else:
        print("Failed to load tools or no tools found.")

    # 测试关闭（如果适用）
    await close_mcp_client_sessions()
    logger.info("--- MCP Client Test Complete ---")

if __name__ == '__main__':
    # 这允许直接运行测试，例如：python -m src.tools.mcp_client
    # 确保您的环境已设置（例如，'uv'命令可用）。
    # E:\github\a_share_mcp的a_share_mcp服务器应该准备好运行。

    # 如果尚未配置，为测试运行设置基本日志记录
    if not logger.hasHandlers():
        import logging
        logging.basicConfig(level=logging.INFO)
        logger.info("Basic logging configured for test run.")

    asyncio.run(_main_test_mcp_client())
