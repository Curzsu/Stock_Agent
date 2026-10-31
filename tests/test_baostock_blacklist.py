"""Offline regression tests: access denials must not cause reconnect storms."""
import importlib
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import time
from types import SimpleNamespace
import unittest
from unittest.mock import Mock, patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "agents"))
from src.utils.baostock_helper import safe_query

# The compatibility entry point and both applications use the same runtime.
helper = importlib.import_module(safe_query.__module__)


def result(code="0", message="success"):
    return SimpleNamespace(error_code=code, error_msg=message, fields=[], next=lambda: False)


class BlacklistTests(unittest.TestCase):
    def setUp(self):
        import baostock.common.context as context
        self.directory = tempfile.TemporaryDirectory()
        self.addCleanup(self.directory.cleanup)
        self.sdk = Mock(login=Mock(return_value=result()))
        for patcher in (
            patch.dict(os.environ, {"FINEX_BAOSTOCK_STATE_DIR": self.directory.name}),
            patch.object(helper, "bs", self.sdk),
            patch.object(helper, "_logged_in", False),
            patch.object(context, "default_socket", Mock(), create=True),
        ):
            patcher.start()
            self.addCleanup(patcher.stop)

    def test_login_blacklist_is_not_retried_or_repeated_by_next_request(self):
        self.sdk.login.return_value = result("10001011", "黑名单用户，请与管理员联系")
        query = Mock(return_value=result())
        for _ in range(3):
            with self.assertRaisesRegex(helper.BaostockDataError, "10001011"):
                helper.safe_query(query)
        self.assertEqual(self.sdk.login.call_count, 1)
        query.assert_not_called()

    def test_query_blacklist_also_opens_circuit_without_reconnect(self):
        query = Mock(return_value=result("10001011", "黑名单用户"))
        for _ in range(2):
            with self.assertRaisesRegex(helper.BaostockDataError, "10001011"):
                helper.safe_query(query)
        self.assertEqual(query.call_count, 1)
        self.assertEqual(self.sdk.login.call_count, 1)

    def test_permission_error_is_not_treated_as_a_network_error(self):
        self.sdk.login.return_value = result("10001002", "用户名或密码错误")
        with self.assertRaisesRegex(helper.BaostockDataError, "10001002"):
            helper.safe_query(Mock())
        self.assertEqual(self.sdk.login.call_count, 1)

    def test_blacklist_state_survives_a_fresh_process(self):
        self.sdk.login.return_value = result("10001011", "黑名单用户")
        with self.assertRaises(helper.BaostockDataError):
            helper.safe_query(Mock())
        code = r'''
import importlib,json,sys
from unittest.mock import Mock
sys.path.insert(0, "agents")
from src.utils.baostock_helper import safe_query
runtime=importlib.import_module(safe_query.__module__)
runtime.bs=Mock(login=Mock(side_effect=RuntimeError("unexpected provider login")))
try: runtime.safe_query(Mock())
except RuntimeError as error: print(json.dumps({"message":str(error),"logins":runtime.bs.login.call_count}))
'''
        child = subprocess.run([sys.executable, "-c", code], cwd=ROOT,
                               capture_output=True, text=True, encoding="utf-8", timeout=15)
        self.assertEqual(child.returncode, 0, child.stderr)
        info = json.loads(child.stdout)
        self.assertEqual(info["logins"], 0)
        self.assertIn("10001011", info["message"])

    def test_expired_circuit_allows_one_request_and_closes_its_connection(self):
        path = Path(self.directory.name) / "blacklist.json"
        path.write_text(json.dumps({"blocked_until": time.time() - 1}), encoding="utf-8")
        query = Mock(return_value=result())
        helper.safe_query(query)
        self.sdk.login.assert_called_once()
        self.sdk.logout.assert_called_once()
        self.assertFalse(helper._logged_in)
        query.assert_called_once()

    def test_corrupt_circuit_state_fails_closed_before_login(self):
        path = Path(self.directory.name) / "blacklist.json"
        path.write_text("not valid json", encoding="utf-8")
        with self.assertRaisesRegex(helper.BaostockDataError, "暂停记录无法读取"):
            helper.safe_query(Mock())
        self.sdk.login.assert_not_called()

    def test_blacklist_state_write_failure_never_retries_provider_login(self):
        self.sdk.login.return_value = result("10001011", "黑名单用户")
        with patch.object(Path, "write_text", side_effect=OSError("disk full")):
            for _ in range(2):
                with self.assertRaisesRegex(helper.BaostockDataError, "10001011"):
                    helper.safe_query(Mock())
        self.sdk.login.assert_called_once()


if __name__ == "__main__":
    unittest.main()
