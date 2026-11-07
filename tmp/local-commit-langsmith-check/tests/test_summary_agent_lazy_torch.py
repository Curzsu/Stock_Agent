"""
C 项回归测试：summary_agent 顶层不再 import torch/transformers。

背景：
summary_agent.py 原本在文件顶层写
    import torch
    from transformers import AutoTokenizer, AutoModelForCausalLM
这两行只在 USE_LOCAL_MODEL=local 分支（本地 FinR1 模型）用到，
但顶层 import 导致每次启动都加载 torch/transformers（约 14 秒），
即使默认走 API 路径也躲不掉。

用户已决定不做微调，本地模型路径不再使用。将这两个 import
下沉到真正使用它们的 load_finr1_model / generate_report_with_finr1
函数体内（延迟加载），API 路径零依赖。

本测试固化清理后的行为契约：
1. import summary_agent 后，torch 不在 sys.modules（顶层未加载）
2. import summary_agent 后，transformers 不在 sys.modules
3. load_finr1_model / generate_report_with_finr1 仍可被引用（功能保留）

为规避 PyO3 uuid_utils 在同进程多次初始化的限制，本测试在
子进程中执行 import，主进程仅断言子进程的输出。
"""
import os
import sys
import subprocess
import unittest

PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
AGENTS_DIR = os.path.join(PROJECT_ROOT, "agents")
PYTHON = sys.executable


class TestSummaryAgentLazyTorch(unittest.TestCase):
    """验证 summary_agent 顶层不再加载 torch/transformers。"""

    def _import_in_subprocess(self):
        """在干净子进程中 import summary_agent，返回 torch/transformers 是否被加载。"""
        script = (
            "import sys\n"
            f"sys.path.insert(0, {AGENTS_DIR!r})\n"
            "import src.agents.summary_agent as m\n"
            "out = []\n"
            "out.append(('torch', 'torch' in sys.modules))\n"
            "out.append(('transformers', 'transformers' in sys.modules))\n"
            "out.append(('has_load_finr1', hasattr(m, 'load_finr1_model')))\n"
            "out.append(('has_generate', hasattr(m, 'generate_report_with_finr1')))\n"
            "for k, v in out:\n"
            "    print(f'{k}={v}')\n"
        )
        env = dict(os.environ)
        env["PYTHONIOENCODING"] = "utf-8"
        r = subprocess.run(
            [PYTHON, "-c", script],
            capture_output=True, text=True, env=env, timeout=120,
        )
        if r.returncode != 0:
            self.fail(f"子进程 import 失败:\n{r.stderr}")
        result = {}
        for line in r.stdout.splitlines():
            if "=" in line:
                k, v = line.split("=", 1)
                result[k] = v == "True"
        return result

    def test_torch_not_loaded_at_import(self):
        """import summary_agent 不应触发 torch 加载。"""
        result = self._import_in_subprocess()
        self.assertIn("torch", result)
        self.assertFalse(
            result["torch"],
            "torch 被顶层 import 加载了，应延迟到 load_finr1_model 内",
        )

    def test_transformers_not_loaded_at_import(self):
        """import summary_agent 不应触发 transformers 加载。"""
        result = self._import_in_subprocess()
        self.assertIn("transformers", result)
        self.assertFalse(
            result["transformers"],
            "transformers 被顶层 import 加载了，应延迟到 load_finr1_model 内",
        )

    def test_local_model_functions_preserved(self):
        """load_finr1_model / generate_report_with_finr1 仍保留（功能未删）。"""
        result = self._import_in_subprocess()
        self.assertTrue(result.get("has_load_finr1"), "load_finr1_model 应保留")
        self.assertTrue(result.get("has_generate"), "generate_report_with_finr1 应保留")


if __name__ == "__main__":
    unittest.main()
