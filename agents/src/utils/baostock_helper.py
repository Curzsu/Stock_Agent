"""
baostock 线程安全访问封装。

背景（P0-2）：
baostock 的 bs.login()/bs.logout() 操作进程级全局连接，不是线程/协程
隔离的。原来 server.py 的 lookup_stock_code_by_name / verify_stock_code_exists
每次调用都 login -> query -> logout，并发请求会互相踢掉对方的 session，
导致 query 返回错误或抛异常。

修复策略：
1. 进程级单例登录：ensure_logged_in() 只在首次调用时 login，之后复用，
   不再反复 login/logout。
2. 互斥锁：safe_query() 在查询期间持锁，保证查询期间全局连接不被破坏。
   （单例登录后其实仍需锁，因为 baostock 的 query 可能不是线程安全的，
   且未来若支持多请求并发查询，锁能避免结果集串台。）
"""
import os
import socket
import threading
import time
from contextlib import contextmanager

import baostock as bs
import baostock.common.context as bs_context
import baostock.util.socketutil as bs_transport

from src.utils.logging_config import setup_logger

logger = setup_logger(__name__)

# baostock 默认创建 socket 时无超时：远程行情服务器不可达/响应异常时，
# bs.login 和各 query 会永久阻塞，导致分析卡在"等待中"永不开始
# （server.py 股票校验阶段在设置 progress=running 之前就调用了 baostock）。
# 这里给 baostock 每次网络操作套一个 socket 超时，超时抛 socket.timeout，
# 由上层 try/except 捕获后降级继续，而不是无限等待。可通过环境变量覆盖。
BAOSTOCK_SOCKET_TIMEOUT = float(os.getenv("BAOSTOCK_SOCKET_TIMEOUT", "30"))


def _with_socket_timeout(fn, *args, timeout=BAOSTOCK_SOCKET_TIMEOUT, **kwargs):
    """在 socket 默认超时保护下调用 fn，结束后恢复原默认超时。

    socket.setdefaulttimeout 会影响后续新建 socket 的默认超时，
    因此必须 try/finally 恢复，避免污染进程内其他网络调用（如 LLM API）。
    """
    old_timeout = socket.getdefaulttimeout()
    socket.setdefaulttimeout(timeout)
    try:
        return fn(*args, **kwargs)
    finally:
        socket.setdefaulttimeout(old_timeout)


# 进程级登录状态
_logged_in = False
_query_lock = threading.Lock()
_CONNECTION_ERRORS = {"10001001", *(f"1000200{i}" for i in range(1, 9))}


class BaostockDataError(RuntimeError):
    """The data service failed; this does not mean a stock does not exist."""


def _remaining_timeout(deadline):
    remaining = deadline - time.monotonic()
    if remaining <= 0:
        raise TimeoutError("baostock 查询超时")
    return remaining


class _CheckedSocket:
    """Detect EOF before the SDK's receive loop can spin on empty reads."""

    def __init__(self, connection, deadline):
        self.connection = connection
        self.deadline = deadline
        self.error = None

    def __getattr__(self, name):
        return getattr(self.connection, name)

    def _call(self, method, *args, **kwargs):
        try:
            self.connection.settimeout(_remaining_timeout(self.deadline))
            value = getattr(self.connection, method)(*args, **kwargs)
            if method == "recv" and value == b"":
                raise ConnectionResetError("baostock 远程连接已关闭")
            return value
        except OSError as exc:
            self.error = exc
            raise

    def send(self, *args, **kwargs):
        return self._call("send", *args, **kwargs)

    def recv(self, *args, **kwargs):
        return self._call("recv", *args, **kwargs)


@contextmanager
def _query_guard(deadline):
    if not _query_lock.acquire(timeout=_remaining_timeout(deadline)):
        raise BaostockDataError("baostock 查询被占用，请稍后重试")
    original_send = bs_transport.send_msg

    def checked_send(*args, **kwargs):
        connection = getattr(bs_context, "default_socket", None)
        if connection is None:
            return original_send(*args, **kwargs)
        checked = _CheckedSocket(connection, deadline)
        bs_context.default_socket = checked
        try:
            response = original_send(*args, **kwargs)
            # BaoStock swallows socket exceptions, including during pagination.
            if checked.error is not None:
                raise checked.error
            return response
        finally:
            if bs_context.default_socket is checked:
                bs_context.default_socket = connection

    # Scope this adapter to serialized BaoStock operations. The SDK creates its
    # login socket internally; wrapping send_msg covers login and every page
    # without replacing socket APIs used by the rest of the application.
    bs_transport.send_msg = checked_send
    try:
        yield
    finally:
        bs_transport.send_msg = original_send
        _query_lock.release()


def _discard_connection():
    """Close a failed transport without sending logout over the broken socket."""
    global _logged_in
    _logged_in = False
    connection = getattr(bs_context, "default_socket", None)
    bs_context.default_socket = None
    if connection is not None:
        try:
            connection.close()
        except OSError:
            pass


def _set_connection_timeout(timeout):
    connection = getattr(bs_context, "default_socket", None)
    if connection is not None:
        connection.settimeout(timeout)


def _ensure_logged_in_locked(deadline):
    global _logged_in
    if _logged_in:
        return
    lg = _with_socket_timeout(bs.login, timeout=_remaining_timeout(deadline))
    if lg.error_code != "0":
        raise BaostockDataError(f"baostock login failed ({lg.error_code}): {lg.error_msg}")
    _set_connection_timeout(_remaining_timeout(deadline))
    _logged_in = True
    logger.info("baostock logged in (singleton session established).")


def ensure_logged_in():
    """Serialize login with queries so reconnection cannot replace an active socket."""
    deadline = time.monotonic() + BAOSTOCK_SOCKET_TIMEOUT
    with _query_guard(deadline):
        try:
            _ensure_logged_in_locked(deadline)
        except Exception:
            _discard_connection()
            raise


class _BufferedResult:
    """BaoStock-compatible cursor backed entirely by local rows."""

    def __init__(self, result, rows):
        self.error_code = result.error_code
        self.error_msg = result.error_msg
        self.fields = list(result.fields)
        self._rows = rows
        self._index = 0

    def next(self):
        return self._index < len(self._rows)

    def get_row_data(self):
        if not self.next():
            return []
        row = self._rows[self._index]
        self._index += 1
        return row


def safe_query(query_fn, *args, **kwargs):
    """在互斥锁保护下执行一次 baostock 查询。

    Args:
        query_fn: 调用 baostock 查询 API 的可调用对象。
        *args, **kwargs: 传给 query_fn 的参数。

    Returns:
        内存结果游标，保留 error_code/error_msg/fields/next/get_row_data 接口。

    ResultData.next() 可能继续请求下一页，因此必须在锁内读完所有分页。
    """
    deadline = time.monotonic() + BAOSTOCK_SOCKET_TIMEOUT
    with _query_guard(deadline):
        for attempt in range(2):
            try:
                _remaining_timeout(deadline)
                _ensure_logged_in_locked(deadline)
                # setdefaulttimeout only affects NEW sockets. The singleton may
                # have been created by an earlier request, so configure it too.
                _set_connection_timeout(_remaining_timeout(deadline))
                result = query_fn(*args, **kwargs)
                rows = []
                while result.error_code == "0":
                    _set_connection_timeout(_remaining_timeout(deadline))
                    if not result.next():
                        break
                    rows.append(list(result.get_row_data()))
                if result.error_code in _CONNECTION_ERRORS:
                    raise BaostockDataError(
                        f"baostock query failed ({result.error_code}): {result.error_msg}")
                return _BufferedResult(result, rows)
            except (OSError, BaostockDataError) as exc:
                _discard_connection()
                if attempt == 1 or time.monotonic() >= deadline:
                    raise BaostockDataError(f"baostock 数据服务连接失败：{exc}") from exc
                logger.warning("baostock connection failed; reconnecting once: %s", exc)
            except Exception:
                _discard_connection()
                raise


def shutdown():
    """进程退出时登出（可选，通常不需要主动调用）。"""
    deadline = time.monotonic() + BAOSTOCK_SOCKET_TIMEOUT
    with _query_guard(deadline):
        if _logged_in:
            try:
                _set_connection_timeout(_remaining_timeout(deadline))
                bs.logout()
            except Exception:
                pass
            finally:
                _discard_connection()
