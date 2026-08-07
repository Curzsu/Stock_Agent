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
import threading

import baostock as bs

from src.utils.logging_config import setup_logger

logger = setup_logger(__name__)

# 进程级登录状态
_logged_in = False
_login_lock = threading.Lock()
_query_lock = threading.Lock()


def ensure_logged_in():
    """确保 baostock 已登录（进程级单例）。

    首次调用执行 bs.login()，后续调用直接返回，不重复登录。
    线程安全：用锁保护首次登录，避免多线程同时 login。
    """
    global _logged_in
    if _logged_in:
        return
    with _login_lock:
        if _logged_in:
            return
        lg = bs.login()
        if lg.error_code != "0":
            raise RuntimeError(f"baostock login failed: {lg.error_msg}")
        _logged_in = True
        logger.info("baostock logged in (singleton session established).")


def safe_query(query_fn, *args, **kwargs):
    """在互斥锁保护下执行一次 baostock 查询。

    Args:
        query_fn: 调用 baostock 查询 API 的可调用对象。
        *args, **kwargs: 传给 query_fn 的参数。

    Returns:
        query_fn 的返回值（通常是 baostock 的 ResultData）。

    确保查询期间没有其他线程干扰全局连接。
    """
    ensure_logged_in()
    with _query_lock:
        return query_fn(*args, **kwargs)


def shutdown():
    """进程退出时登出（可选，通常不需要主动调用）。"""
    global _logged_in
    with _login_lock:
        if _logged_in:
            try:
                bs.logout()
            except Exception:
                pass
            _logged_in = False
