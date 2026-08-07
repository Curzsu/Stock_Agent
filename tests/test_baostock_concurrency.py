"""
P0-2 回归测试：baostock 全局登录并发竞态。

背景：
baostock 的 bs.login()/bs.logout() 操作进程级全局连接。server.py 的
lookup_stock_code_by_name / verify_stock_code_exists 每次调用都
login -> query -> logout，两个并发请求会互相踢掉对方的 session，
导致 query 返回错误或抛异常。

本测试用 mock baostock 复现该竞态，并验证修复后（进程级单例登录 + 互斥锁）
并发调用不再互相干扰。

测试目标模块：agents/src/utils/baostock_helper.py（待创建）
提供线程安全的 baostock 访问封装：
  - ensure_logged_in(): 进程级单例登录
  - safe_query(func, *args, **kwargs): 互斥锁保护下的查询
"""
import sys
import os
import time
import types
import threading
import unittest
from unittest.mock import patch

PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, PROJECT_ROOT)
sys.path.insert(0, os.path.join(PROJECT_ROOT, "agents"))


def _install_fake_baostock():
    """
    安装模拟 baostock，真实反映全局连接状态，并在 query 中加 sleep
    放大竞态窗口，确保并发调用一定会重叠。
    """
    fake = types.ModuleType("baostock")
    state = {"_connected": False}

    class _ResultData:
        def __init__(self, error_code="0", error_msg="ok"):
            self.error_code = error_code
            self.error_msg = error_msg
            self.fields = ["code", "code_name"]

        def next(self):
            return False

        def get_row_data(self):
            return []

    def login(user_id="anonymous", password="123456", options=0):
        state["_connected"] = True
        return _ResultData()

    def logout(user_id="anonymous"):
        state["_connected"] = False
        return _ResultData()

    def query_stock_basic(code=None):
        # 放大竞态窗口：query 期间 sleep，让其他线程有机会 logout
        time.sleep(0.05)
        if not state["_connected"]:
            # session 已被别的线程踢掉
            return _ResultData(error_code="10001", error_msg="not logged in")
        rs = _ResultData()
        if code in (None, "sh.600519", "sz.000001"):
            # 有数据：用游标实现 next()，第一次返回 True，之后 False（避免死循环）
            rows = [["sh.600519", "贵州茅台"]]
            idx = {"i": 0}

            def _next():
                if idx["i"] < len(rows):
                    idx["i"] += 1
                    return True
                return False

            def _get_row():
                return rows[idx["i"] - 1] if idx["i"] > 0 else []

            rs.next = _next
            rs.get_row_data = _get_row
        return rs

    fake.login = login
    fake.logout = logout
    fake.query_stock_basic = query_stock_basic
    fake._state = state
    return fake


class TestBaostockHelperConcurrency(unittest.TestCase):
    """验证 baostock helper 在并发下不互相干扰。"""

    def _import_helper(self, fake_bs):
        """用 fake baostock 导入 helper 模块（强制重载）。"""
        with patch.dict(sys.modules, {"baostock": fake_bs}):
            # 清除缓存确保用 fake 重新导入
            for mod in ("src.utils.baostock_helper", "backend.server"):
                sys.modules.pop(mod, None)
            import src.utils.baostock_helper as helper
            # 强制让 helper 引用的 bs 是 fake
            helper.bs = fake_bs
            return helper

    def test_concurrent_safe_query_does_not_interfere(self):
        """
        RED: 多线程并发调用 safe_query，不应出现 'not logged in' 错误。

        修复前（裸 login/query/logout）：并发下互相踢，部分调用拿到 10001。
        修复后（单例登录 + 互斥锁）：所有调用都成功。
        """
        fake_bs = _install_fake_baostock()
        helper = self._import_helper(fake_bs)

        errors = []
        ok_count = 0
        ok_lock = threading.Lock()
        N_THREADS = 20

        def worker(i):
            nonlocal ok_count
            try:
                def query_fn():
                    return fake_bs.query_stock_basic(code="sh.600519")

                rs = helper.safe_query(query_fn)
                if rs.error_code != "0":
                    errors.append((i, f"error_code={rs.error_code}"))
                else:
                    with ok_lock:
                        ok_count += 1
            except Exception as e:
                errors.append((i, f"{type(e).__name__}: {e}"))

        threads = [threading.Thread(target=worker, args=(i,)) for i in range(N_THREADS)]
        for t in threads:
            t.start()
        for t in threads:
            t.join()

        self.assertEqual(len(errors), 0,
                         f"并发调用出现竞态错误（共{len(errors)}个）：{errors[:5]}")
        self.assertEqual(ok_count, N_THREADS,
                         f"仅{ok_count}/{N_THREADS} 成功，其余因竞态失败")

    def test_ensure_logged_in_is_idempotent_and_singleton(self):
        """
        RED: ensure_logged_in 应只登录一次（单例），重复调用不重复 login。
        """
        fake_bs = _install_fake_baostock()
        helper = self._import_helper(fake_bs)

        login_count_before = self._count_logins(fake_bs)
        helper.ensure_logged_in()
        helper.ensure_logged_in()
        helper.ensure_logged_in()
        login_count_after = self._count_logins(fake_bs)

        # 单例：多次 ensure 只应登录一次（或第一次已登录则不再 login）
        self.assertLessEqual(login_count_after - login_count_before, 1,
                             "ensure_logged_in 应是单例，不应重复 login")

    def _count_logins(self, fake_bs):
        """计数 login 被调用的次数。"""
        # 用 mock 包装 login 计数
        original = fake_bs.login
        counter = {"n": 0}

        def counting_login(*args, **kwargs):
            counter["n"] += 1
            return original(*args, **kwargs)

        fake_bs.login = counting_login
        # 重新导入 helper 让它用 counting 版本
        import src.utils.baostock_helper as helper
        helper.bs = fake_bs
        helper.ensure_logged_in()
        return counter["n"]


class TestServerFunctionsConcurrency(unittest.TestCase):
    """验证 server.py 的 lookup/verify 函数改造后在并发下安全。"""

    # 类级共享：只导入 server 一次，避免 PyO3 (uuid_utils) 重复初始化崩溃
    _srv = None
    _shared_fake_bs = None

    @classmethod
    def setUpClass(cls):
        """整个类只导入一次 server，用 fake baostock。"""
        fake_bs = _install_fake_baostock()
        # 重置 helper 单例状态
        import src.utils.baostock_helper as bh
        bh._logged_in = False
        bh.bs = fake_bs
        with patch.dict(sys.modules, {"baostock": fake_bs}):
            import backend.server as srv
            srv.bs = fake_bs
            bh.bs = fake_bs
            bh._logged_in = False
        cls._srv = srv
        cls._shared_fake_bs = fake_bs

    def setUp(self):
        """每个测试前重置 helper 单例登录状态，确保测试独立。"""
        import src.utils.baostock_helper as bh
        bh._logged_in = False
        # fake_bs 状态重置
        self._shared_fake_bs._state["_connected"] = False

    def test_server_verify_concurrent_safe(self):
        """server.verify_stock_code_exists 并发调用应全部成功，无误判。"""
        srv = self._srv

        errors = []
        results = []
        ok_lock = threading.Lock()
        N_THREADS = 20

        def worker(i):
            try:
                exists, name = srv.verify_stock_code_exists("sh.600519")
                with ok_lock:
                    results.append((i, exists))
            except Exception as e:
                with ok_lock:
                    errors.append((i, f"{type(e).__name__}: {e}"))

        threads = [threading.Thread(target=worker, args=(i,)) for i in range(N_THREADS)]
        for t in threads:
            t.start()
        for t in threads:
            t.join()

        self.assertEqual(len(errors), 0, f"并发异常：{errors[:3]}")
        self.assertEqual(len(results), N_THREADS)
        for i, exists in results:
            self.assertTrue(exists, f"线程{i}因竞态误判股票不存在")

    def test_server_lookup_concurrent_safe(self):
        """server.lookup_stock_code_by_name 并发调用应全部返回正确结果。"""
        srv = self._srv

        errors = []
        none_count = 0
        ok_lock = threading.Lock()
        N_THREADS = 20

        def worker(i):
            nonlocal none_count
            try:
                code, name = srv.lookup_stock_code_by_name("贵州茅台")
                with ok_lock:
                    if code is None:
                        none_count += 1
            except Exception as e:
                with ok_lock:
                    errors.append((i, f"{type(e).__name__}: {e}"))

        threads = [threading.Thread(target=worker, args=(i,)) for i in range(N_THREADS)]
        for t in threads:
            t.start()
        for t in threads:
            t.join()

        self.assertEqual(len(errors), 0, f"lookup 并发异常：{errors[:3]}")
        self.assertEqual(none_count, 0, f"{none_count}/{N_THREADS} 线程因竞态误判未找到")


if __name__ == "__main__":
    unittest.main(verbosity=2)
