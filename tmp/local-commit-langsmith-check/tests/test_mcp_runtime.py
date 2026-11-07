import subprocess
import unittest
from pathlib import Path

from packaging.version import Version


WORKSPACE = Path(__file__).resolve().parents[1]


class TestMcpRuntime(unittest.TestCase):
    def test_baostock_runtime_uses_non_hanging_release(self):
        completed = subprocess.run(
            [
                "uv",
                "run",
                "--directory",
                str(WORKSPACE / "mcp-server"),
                "python",
                "-c",
                "import importlib.metadata as m; print(m.version('baostock'))",
            ],
            check=True,
            capture_output=True,
            text=True,
            timeout=30,
        )

        self.assertGreaterEqual(Version(completed.stdout.strip()), Version("0.9.3"))


if __name__ == "__main__":
    unittest.main()
