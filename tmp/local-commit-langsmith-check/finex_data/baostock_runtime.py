"""Serialize entire BaoStock sessions across Web and MCP processes.

No provider socket survives the cross-process lease. A successful query is fully
buffered before logout/close. A durable blacklist circuit is shared by both
entry points and survives application restarts.
"""
import errno
import json
import logging
import math
import os
import socket
import sys
import threading
import time
from contextlib import contextmanager, redirect_stdout
from datetime import datetime
from pathlib import Path

import baostock as bs
import baostock.common.context as bs_context
import baostock.util.socketutil as bs_transport

logger = logging.getLogger(__name__)

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
_local_blacklists = {}
_CONNECTION_ERRORS = {"10001001", *(f"1000200{i}" for i in range(1, 9))}


class BaostockDataError(RuntimeError):
    """The data service failed; this does not mean a stock does not exist."""

    def __init__(self, message, *, code="", retryable=True):
        super().__init__(message)
        self.code = str(code)
        self.retryable = retryable


class BaostockBlacklistedError(BaostockDataError):
    """Provider access denial; never retry while the local circuit is open."""

    def __init__(self, blocked_until):
        self.blocked_until = blocked_until
        until = datetime.fromtimestamp(blocked_until).strftime("%Y-%m-%d %H:%M:%S")
        super().__init__(
            f"baostock 已限制当前出口 IP（10001011：黑名单用户）。"
            f"已暂停请求至 {until}（本机时间）；此为本地保护期限，官方可能限制更久。"
            "请到 https://www.baostock.com/blacklist 查询实际释放时间，或联系官方管理员。"
            "重复分析或重启项目不会解除官方限制。",
            code="10001011", retryable=False,
        )


def _state_directory():
    configured = os.getenv("FINEX_BAOSTOCK_STATE_DIR")
    directory = Path(configured).expanduser().resolve() if configured else Path(__file__).resolve().parents[1] / ".runtime" / "baostock"
    directory.mkdir(parents=True, exist_ok=True)
    return directory


def _cooldown_seconds():
    value = float(os.getenv("BAOSTOCK_BLACKLIST_COOLDOWN_SECONDS", "21600"))
    if not math.isfinite(value) or value < 60:
        raise BaostockDataError("BAOSTOCK_BLACKLIST_COOLDOWN_SECONDS 必须是至少 60 秒的有限数值。", retryable=False)
    return value


def _check_blacklist():
    path = _state_directory() / "blacklist.json"
    local_until = _local_blacklists.get(str(path), 0)
    if time.time() < local_until:
        raise BaostockBlacklistedError(local_until)
    if not path.exists():
        return
    try:
        until = float(json.loads(path.read_text(encoding="utf-8"))["blocked_until"])
        if not math.isfinite(until):
            raise ValueError("invalid blocked_until")
    except (OSError, ValueError, KeyError, TypeError) as exc:
        raise BaostockDataError(f"baostock 本地暂停记录无法读取，请检查 {path}：{exc}", retryable=False) from exc
    if time.time() < until:
        raise BaostockBlacklistedError(until)


def _raise_provider_error(code, message, phase):
    if str(code) == "10001011":
        until = time.time() + _cooldown_seconds()
        path = _state_directory() / "blacklist.json"
        _local_blacklists[str(path)] = until
        temporary = path.with_suffix(".tmp")
        try:
            temporary.write_text(json.dumps({"code": str(code), "message": message, "blocked_until": until}, ensure_ascii=False), encoding="utf-8")
            temporary.replace(path)
        except OSError:
            logger.error("无法保存 baostock 暂停记录 %s；本进程仍暂停请求。", path, exc_info=True)
        raise BaostockBlacklistedError(until)
    raise BaostockDataError(f"baostock {phase} failed ({code}): {message}",
                            code=code, retryable=str(code) in _CONNECTION_ERRORS)


@contextmanager
def _process_lease(deadline):
    """An OS lock is released on crashes; never delete its stable lock file."""
    with (_state_directory() / "access.lock").open("a+b") as stream:
        if stream.tell() == 0:
            stream.write(b"\0")
            stream.flush()
        while True:
            _remaining_timeout(deadline)
            try:
                if os.name == "nt":
                    import msvcrt
                    stream.seek(0)
                    msvcrt.locking(stream.fileno(), msvcrt.LK_NBLCK, 1)
                else:
                    import fcntl
                    fcntl.flock(stream.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
                break
            except OSError as exc:
                if exc.errno not in {errno.EACCES, errno.EAGAIN, errno.EDEADLK}:
                    raise
                time.sleep(min(.05, _remaining_timeout(deadline)))
        try:
            yield
        finally:
            if os.name == "nt":
                stream.seek(0)
                msvcrt.locking(stream.fileno(), msvcrt.LK_UNLCK, 1)
            else:
                fcntl.flock(stream.fileno(), fcntl.LOCK_UN)


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
        with _process_lease(deadline):
            try:
                _check_blacklist()
                yield
            finally:
                _end_session(deadline)
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
    # BaoStock prints login/logout messages. Send those to stderr so MCP's
    # stdout remains a JSON-RPC channel; do not replace OS file descriptors.
    with redirect_stdout(sys.stderr):
        lg = _with_socket_timeout(bs.login, timeout=_remaining_timeout(deadline))
    if lg.error_code != "0":
        _raise_provider_error(lg.error_code, lg.error_msg, "login")
    _set_connection_timeout(_remaining_timeout(deadline))
    _logged_in = True
    logger.debug("baostock session established under process lease.")


def _end_session(deadline):
    try:
        if _logged_in and time.monotonic() < deadline:
            _set_connection_timeout(_remaining_timeout(deadline))
            with redirect_stdout(sys.stderr):
                _with_socket_timeout(bs.logout, timeout=_remaining_timeout(deadline))
    except Exception:
        logger.debug("BaoStock logout failed; closing transport locally.", exc_info=True)
    finally:
        _discard_connection()


def ensure_logged_in():
    """Compatibility probe: validate access, then release the provider session.

    Call safe_query directly for real work; it owns login and buffered reads.
    """
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
    SDK diagnostics belong on stderr, including query and pagination failures.
    """
    deadline = time.monotonic() + BAOSTOCK_SOCKET_TIMEOUT
    with _query_guard(deadline), redirect_stdout(sys.stderr):
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
                if result.error_code == "10001011" or result.error_code in _CONNECTION_ERRORS:
                    _raise_provider_error(result.error_code, result.error_msg, "query")
                return _BufferedResult(result, rows)
            except (OSError, BaostockDataError) as exc:
                _discard_connection()
                if isinstance(exc, BaostockDataError) and not exc.retryable:
                    raise
                if attempt == 1 or time.monotonic() >= deadline:
                    raise BaostockDataError(f"baostock 数据服务连接失败：{exc}") from exc
                logger.warning("baostock connection failed; reconnecting once: %s", exc)
            except Exception:
                _discard_connection()
                raise


def shutdown():
    """Compatibility cleanup; successful queries already close their sessions."""
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
