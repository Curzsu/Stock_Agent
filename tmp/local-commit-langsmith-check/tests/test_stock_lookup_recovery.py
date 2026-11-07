"""Regression coverage for name lookup outages and stale BaoStock sessions."""
import asyncio
import socket
import sys
import threading
import tempfile
import time
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock, patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "agents"))

from backend import server
from finex_data import baostock_runtime as helper


def result(rows=(), error_code="0", error_msg="success"):
    cursor = iter(rows)
    current = []

    def next_row():
        nonlocal current
        current = next(cursor, None)
        return current is not None

    return SimpleNamespace(
        error_code=error_code, error_msg=error_msg,
        fields=["code", "code_name"], next=next_row,
        get_row_data=lambda: current,
    )


class TestConnectionRecovery(unittest.TestCase):
    def setUp(self):
        import baostock.common.context as context
        directory = tempfile.TemporaryDirectory()
        self.addCleanup(directory.cleanup)
        self.socket = Mock()
        self.bs = Mock(login=Mock(return_value=result()))
        for target, name, value in (
            (helper, "bs", self.bs),
            (helper, "_logged_in", False),
            (context, "default_socket", self.socket),
        ):
            patcher = patch.object(target, name, value, create=True)
            patcher.start()
            self.addCleanup(patcher.stop)
        environment = patch.dict("os.environ", {"FINEX_BAOSTOCK_STATE_DIR": directory.name})
        environment.start()
        self.addCleanup(environment.stop)

    def test_network_error_reconnects_and_repeats_read_once(self):
        query = Mock(side_effect=[result(error_code="10002007"), result([["sh.600900", "长江电力"]])])
        response = helper.safe_query(query)
        self.assertEqual(response.error_code, "0")
        self.assertEqual(self.bs.login.call_count, 2)
        self.assertEqual(query.call_count, 2)
        self.socket.close.assert_called_once()

    def test_connection_reset_is_retried(self):
        query = Mock(side_effect=[ConnectionResetError("connection reset"), result()])
        self.assertEqual(helper.safe_query(query).error_code, "0")
        self.assertEqual(self.bs.login.call_count, 2)

    def test_failed_recovery_is_bounded_and_invalidates_session(self):
        query = Mock(return_value=result(error_code="10002007", error_msg="网络接收错误"))
        with self.assertRaisesRegex(RuntimeError, "baostock.*10002007"):
            helper.safe_query(query)
        self.assertEqual(query.call_count, 2)
        self.assertFalse(helper._logged_in)

    def test_existing_connection_receives_socket_timeout(self):
        helper._logged_in = True
        original_timeout = socket.getdefaulttimeout()
        helper.safe_query(lambda: result())
        self.assertGreater(self.socket.settimeout.call_args.args[0], 0)
        self.assertLessEqual(self.socket.settimeout.call_args.args[0], helper.BAOSTOCK_SOCKET_TIMEOUT)
        self.assertEqual(socket.getdefaulttimeout(), original_timeout)

    def test_query_lock_wait_is_bounded(self):
        errors = []

        def run_query():
            try:
                helper.safe_query(lambda: result())
            except RuntimeError as exc:
                errors.append(str(exc))

        helper._query_lock.acquire()
        try:
            with patch.object(helper, "BAOSTOCK_SOCKET_TIMEOUT", 0.01):
                worker = threading.Thread(target=run_query, daemon=True)
                worker.start()
                worker.join(timeout=0.3)
                completed = not worker.is_alive()
        finally:
            helper._query_lock.release()
            worker.join(timeout=1)
        self.assertTrue(completed, "query lock must have a bounded wait")
        self.assertEqual(len(errors), 1)
        self.assertIn("baostock", errors[0])

    def test_failed_pagination_discards_partial_rows_before_retry(self):
        first = result([["sh.600000", "partial"]])
        first_next = first.next

        def broken_page():
            if first_next():
                return True
            first.error_code = "10002007"
            return False

        first.next = broken_page
        query = Mock(side_effect=[first, result([["sh.600900", "长江电力"]])])
        response = helper.safe_query(query)
        self.assertTrue(response.next())
        self.assertEqual(response.get_row_data(), ["sh.600900", "长江电力"])
        self.assertFalse(response.next())

    def test_orderly_eof_is_detected_before_sdk_can_spin(self):
        import baostock.common.context as context
        import baostock.util.socketutil as transport
        # The real SDK loops on b''. The sentinel bounds the OLD behavior so
        # this regression test cannot itself hang before the fix is applied.
        self.socket.recv.side_effect = [b"", b"", OSError("test sentinel")]
        first_send = transport.send_msg
        calls = []

        def query():
            calls.append(True)
            if len(calls) == 1:
                transport.send_msg("request")
                return result(error_code="10002007")
            return result([["sh.600900", "长江电力"]])

        response = helper.safe_query(query)
        self.assertEqual(response.error_code, "0")
        self.assertEqual(self.socket.recv.call_count, 1, "EOF must stop at the first empty read")
        self.assertIs(transport.send_msg, first_send, "SDK function must be restored")
        self.assertIsNone(context.default_socket)

    def test_swallowed_pagination_eof_triggers_recovery(self):
        import baostock.util.socketutil as transport
        self.socket.recv.side_effect = [b"", OSError("test sentinel")]
        partial = result([["sh.600000", "partial"]])
        next_row = partial.next

        def next_page():
            if next_row():
                return True
            transport.send_msg("next page")
            return False  # BaoStock leaves error_code == '0' on receive failure.

        partial.next = next_page
        query = Mock(side_effect=[partial, result([["sh.600900", "长江电力"]])])
        response = helper.safe_query(query)
        self.assertTrue(response.next())
        self.assertEqual(response.get_row_data(), ["sh.600900", "长江电力"])
        self.assertEqual(query.call_count, 2)

    def test_recovery_does_not_start_after_query_budget_is_exhausted(self):
        clock = [0.0]
        def slow_failure():
            # Advance a controlled clock after the query starts; Windows login /
            # logging overhead must not exhaust a 30ms budget before this point.
            clock[0] = 0.06
            raise ConnectionResetError("slow failure")

        query = Mock(side_effect=slow_failure)
        with patch.object(helper, "BAOSTOCK_SOCKET_TIMEOUT", 0.03), \
             patch.object(helper.time, "monotonic", side_effect=lambda: clock[0]):
            with self.assertRaises(RuntimeError):
                helper.safe_query(query)
        self.assertEqual(query.call_count, 1)
        self.assertFalse(helper._logged_in)


class TestStockLookup(unittest.TestCase):
    def test_name_lookup_filters_on_server_and_keeps_exact_match(self):
        rows = [["sh.600901", "长江电力测试"], ["sh.600900", "长江电力"]]
        with patch.object(server, "safe_query", side_effect=lambda fn: fn()), \
             patch.object(server.bs, "query_stock_basic", return_value=result(rows)) as query:
            self.assertEqual(server.lookup_stock_code_by_name("长江电力"), ("600900", "长江电力"))
        query.assert_called_once_with(code_name="长江电力")

    def test_name_lookup_does_not_turn_service_error_into_unknown_company(self):
        with patch.object(server, "safe_query", return_value=result(error_code="10002007")):
            with self.assertRaisesRegex(RuntimeError, "baostock"):
                server.lookup_stock_code_by_name("长江电力")

    def test_verify_does_not_turn_service_error_into_delisted_stock(self):
        with patch.object(server, "safe_query", return_value=result(error_code="10002007")):
            with self.assertRaisesRegex(RuntimeError, "baostock"):
                server.verify_stock_code_exists("sh.600900")

    def test_workflow_reports_data_service_outage(self):
        session = server.AnalysisStatus(analysis_id="outage", status="pending", progress={})
        with patch.dict(server.analysis_sessions, {"outage": session}), \
             patch.object(server, "lookup_stock_code_by_name", side_effect=helper.BaostockDataError("baostock 网络接收错误")), \
             patch.object(server, "build_workflow") as build:
            asyncio.run(server.run_analysis_workflow("outage", "长江电力"))
        self.assertEqual(session.status, "error")
        self.assertIn("行情数据服务", session.error)
        self.assertNotIn("未找到", session.error)
        self.assertIsNotNone(session.end_time)
        build.assert_not_called()

    def test_blacklist_message_explains_pause_instead_of_suggesting_retry(self):
        session = server.AnalysisStatus(analysis_id="blocked", status="pending", progress={})
        error = helper.BaostockBlacklistedError(time.time() + 21600)
        with patch.dict(server.analysis_sessions, {"blocked": session}), \
             patch.object(server, "lookup_stock_code_by_name", side_effect=error), \
             patch.object(server, "build_workflow") as build:
            asyncio.run(server.run_analysis_workflow("blocked", "长江电力"))
        self.assertEqual(session.status, "error")
        self.assertIn("访问已暂停", session.error)
        self.assertNotIn("请稍后重试", session.error)
        self.assertIn("blacklist", session.error)
        self.assertIsNotNone(session.end_time)
        build.assert_not_called()


if __name__ == "__main__":
    unittest.main(verbosity=2)
