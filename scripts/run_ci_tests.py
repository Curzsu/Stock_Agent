"""Run offline unittest files in separate processes to isolate their src packages."""

import argparse
import os
import subprocess
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
MCP_TEST = "test_mcp_data_fallbacks.py"
RUNTIME_TEST = "test_mcp_runtime.py"
DIAGNOSTICS = {"test_mcp_direct.py", "test_langchain_mcp.py"}
CHILD_RUNNER = """
import sys, unittest
from pathlib import Path
path = Path(sys.argv[1])
suite = unittest.defaultTestLoader.discover(str(path.parent), pattern=path.name)
if suite.countTestCases() == 0:
    sys.exit('No tests collected: ' + str(path))
result = unittest.TextTestRunner(verbosity=2).run(suite)
sys.exit(0 if result.wasSuccessful() else 1)
"""


def select_tests(root: Path, suite: str) -> list[Path]:
    tests = root / "tests"
    if suite == "runtime":
        return [tests / RUNTIME_TEST]
    if suite == "mcp":
        return sorted((root / "mcp-server/tests").rglob("test_*.py")) + [tests / MCP_TEST]
    excluded = {tests / name for name in DIAGNOSTICS | {MCP_TEST, RUNTIME_TEST}}
    return sorted(path for path in tests.rglob("test_*.py") if path not in excluded)


def run_file(path: Path, timeout: float = 180) -> int:
    print(f"\n>>> {path}", flush=True)
    try:
        completed = subprocess.run(
            [sys.executable, "-c", CHILD_RUNNER, str(path.resolve())],
            cwd=ROOT,
            env={
                **os.environ,
                "PYTHONUTF8": "1",
                "PYTHONIOENCODING": "utf-8",
                "PYTHON_DOTENV_DISABLED": "1",
                "USE_LOCAL_MODEL": "api",
                "LANGSMITH_TRACING": "false",
            },
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=timeout,
        )
    except subprocess.TimeoutExpired:
        print(f"FAIL: timed out after {timeout}s", file=sys.stderr)
        return 1
    sys.stdout.write(completed.stdout)
    sys.stderr.write(completed.stderr)
    return completed.returncode


def run_suite(files: list[Path], timeout: float = 180) -> int:
    if not files:
        print("FAIL: no test files selected", file=sys.stderr)
        return 1
    for path in files:
        if run_file(path, timeout) != 0:
            return 1
    print(f"\nPassed {len(files)} test files.", flush=True)
    return 0


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("suite", choices=("app", "mcp", "runtime"))
    args = parser.parse_args()
    return run_suite(select_tests(ROOT, args.suite))


if __name__ == "__main__":
    sys.exit(main())
