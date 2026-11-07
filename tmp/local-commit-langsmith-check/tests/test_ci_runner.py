"""The CI runner must never turn missing, broken or hanging tests green."""

import importlib.util
import contextlib
import io
import tempfile
import textwrap
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
SPEC = importlib.util.spec_from_file_location("run_ci_tests", ROOT / "scripts/run_ci_tests.py")
runner = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(runner)


class TestCiRunner(unittest.TestCase):
    def setUp(self):
        self.directory = tempfile.TemporaryDirectory(dir=ROOT)
        self.addCleanup(self.directory.cleanup)
        self.root = Path(self.directory.name)
        output = contextlib.ExitStack()
        self.addCleanup(output.close)
        output.enter_context(contextlib.redirect_stdout(io.StringIO()))
        output.enter_context(contextlib.redirect_stderr(io.StringIO()))

    def write_test(self, name, body):
        path = self.root / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(textwrap.dedent(body), encoding="utf-8")
        return path

    def test_passing_file_succeeds_without_a_main_block(self):
        path = self.write_test("test_pass.py", """
            import unittest
            class TestExample(unittest.TestCase):
                def test_value(self):
                    self.assertEqual(2 + 2, 4)
        """)
        self.assertEqual(runner.run_file(path), 0)

    def test_assertion_failure_is_not_success(self):
        path = self.write_test("test_fail.py", """
            import unittest
            class TestExample(unittest.TestCase):
                def test_value(self):
                    self.fail('intentional fixture failure')
        """)
        self.assertNotEqual(runner.run_file(path), 0)

    def test_file_without_tests_is_not_success(self):
        path = self.write_test("test_empty.py", "VALUE = 42")
        self.assertNotEqual(runner.run_file(path), 0)

    def test_successful_exit_during_collection_is_not_success(self):
        path = self.write_test("test_exit.py", "raise SystemExit(0)")
        self.assertNotEqual(runner.run_file(path), 0)

    def test_hanging_file_fails_within_timeout(self):
        path = self.write_test("test_hang.py", "import time; time.sleep(30)")
        self.assertNotEqual(runner.run_file(path, timeout=0.2), 0)

    def test_module_state_does_not_leak_between_files(self):
        first = self.write_test("test_first.py", """
            import sys, unittest
            sys.modules['ci_isolation_probe'] = object()
            class TestFirst(unittest.TestCase):
                def test_value(self):
                    self.assertIn('ci_isolation_probe', sys.modules)
        """)
        second = self.write_test("test_second.py", """
            import sys, unittest
            class TestSecond(unittest.TestCase):
                def test_value(self):
                    self.assertNotIn('ci_isolation_probe', sys.modules)
        """)
        self.assertEqual(runner.run_file(first), 0)
        self.assertEqual(runner.run_file(second), 0)

    def test_suites_discover_new_files_and_route_mcp_tests(self):
        for name in (
            "tests/test_new.py", "tests/nested/test_future.py",
            "tests/test_mcp_data_fallbacks.py", "tests/test_mcp_runtime.py",
            "tests/test_mcp_direct.py", "tests/test_langchain_mcp.py",
            "mcp-server/tests/test_new_mcp.py",
        ):
            self.write_test(name, "")
        self.assertEqual(
            {p.relative_to(self.root).as_posix() for p in runner.select_tests(self.root, "app")},
            {"tests/test_new.py", "tests/nested/test_future.py"},
        )
        self.assertEqual(
            {p.relative_to(self.root).as_posix() for p in runner.select_tests(self.root, "mcp")},
            {"mcp-server/tests/test_new_mcp.py", "tests/test_mcp_data_fallbacks.py"},
        )
        self.assertEqual(
            runner.select_tests(self.root, "runtime"),
            [self.root / "tests/test_mcp_runtime.py"],
        )

    def test_empty_selection_is_not_success(self):
        self.assertNotEqual(runner.run_suite([], timeout=1), 0)

    def test_suite_propagates_a_file_failure(self):
        path = self.write_test("test_failure.py", """
            import unittest
            class TestExample(unittest.TestCase):
                def test_value(self):
                    self.fail('intentional fixture failure')
        """)
        self.assertNotEqual(runner.run_suite([path]), 0)


if __name__ == "__main__":
    unittest.main(verbosity=2)
