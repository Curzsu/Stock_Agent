"""
配置 API Key 功能:后端 /api/config 端点测试。

背景:
首页新增"配置 API Key"按钮,弹窗可查看(脱敏)和修改当前 API 配置。
后端提供两个端点:
  GET  /api/config  -- 返回当前配置(api_key 脱敏)
  POST /api/config  -- 更新 os.environ(立即生效)+ 写 .env(持久化)

本测试用 FastAPI TestClient 验证端点行为,不碰真实 agents/.env:
- 持久化测试用 monkeypatch 把 server.env_path 指向临时文件
"""
import os
import sys
import tempfile
import unittest
from unittest.mock import patch, MagicMock, AsyncMock

PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, PROJECT_ROOT)
sys.path.insert(0, os.path.join(PROJECT_ROOT, "agents"))


class TestGetApiConfig(unittest.TestCase):
    """GET /api/config:返回当前配置,api_key 脱敏。"""

    def setUp(self):
        # 延迟导入 server,避免与同进程其他 langchain 测试套件冲突
        from backend import server
        from fastapi.testclient import TestClient
        self.server = server
        self.client = TestClient(server.app)

    def _set_env(self, **kwargs):
        """设置/清理三个配置变量。传 value=None 表示删除。"""
        defaults = {
            "OPENAI_COMPATIBLE_API_KEY": None,
            "OPENAI_COMPATIBLE_BASE_URL": None,
            "OPENAI_COMPATIBLE_MODEL": None,
        }
        defaults.update(kwargs)
        for key, val in defaults.items():
            if val is None:
                os.environ.pop(key, None)
            else:
                os.environ[key] = val

    def test_get_config_returns_masked_values(self):
        """GET /api/config 返回 3 个字段,api_key 被脱敏(含 ***)。"""
        self._set_env(
            OPENAI_COMPATIBLE_API_KEY="sk-abcdefghij1234",
            OPENAI_COMPATIBLE_BASE_URL="https://api.example.com/v1",
            OPENAI_COMPATIBLE_MODEL="gpt-test",
        )
        try:
            resp = self.client.get("/api/config")
            self.assertEqual(resp.status_code, 200)
            data = resp.json()
            self.assertIn("api_key", data)
            self.assertIn("base_url", data)
            self.assertIn("model", data)
            # base_url / model 原样返回
            self.assertEqual(data["base_url"], "https://api.example.com/v1")
            self.assertEqual(data["model"], "gpt-test")
            # api_key 被脱敏:不含完整明文,含 ***
            self.assertNotIn("abcdefghij1234", data["api_key"])
            self.assertIn("***", data["api_key"])
        finally:
            self._set_env()

    def test_get_config_when_unset(self):
        """三个变量都未配置时,GET 不报错,返回空串。"""
        self._set_env()  # 全部删除
        try:
            resp = self.client.get("/api/config")
            self.assertEqual(resp.status_code, 200)
            data = resp.json()
            self.assertEqual(data["api_key"], "")
            self.assertEqual(data["base_url"], "")
            self.assertEqual(data["model"], "")
        finally:
            self._set_env()


class TestPostApiConfig(unittest.TestCase):
    """POST /api/config:更新 os.environ(立即生效)+ 写 .env(持久化)。"""

    def setUp(self):
        from backend import server
        from fastapi.testclient import TestClient
        self.server = server
        self.client = TestClient(server.app)
        # 用临时 .env,绝不污染真实 agents/.env
        self._tmpdir = tempfile.TemporaryDirectory()
        self._tmp_env = os.path.join(self._tmpdir.name, ".env")
        # 写入初始配置
        with open(self._tmp_env, "w", encoding="utf-8") as f:
            f.write("OPENAI_COMPATIBLE_API_KEY=sk-old-key-1234\n")
            f.write("OPENAI_COMPATIBLE_BASE_URL=https://old.example.com/v1\n")
            f.write("OPENAI_COMPATIBLE_MODEL=old-model\n")
        # patch env_path 指向临时文件
        self._env_path_patch = patch.object(server, "env_path", self._tmp_env)
        self._env_path_patch.start()

    def tearDown(self):
        self._env_path_patch.stop()
        self._tmpdir.cleanup()
        # 清理 os.environ 里的测试值
        for k in ("OPENAI_COMPATIBLE_API_KEY", "OPENAI_COMPATIBLE_BASE_URL",
                  "OPENAI_COMPATIBLE_MODEL"):
            os.environ.pop(k, None)

    def test_post_config_updates_os_environ(self):
        """POST 新值后,os.environ 立即更新(下次分析就能读到)。"""
        resp = self.client.post("/api/config", json={
            "api_key": "sk-new-key-5678",
            "base_url": "https://new.example.com/v1",
            "model": "new-model",
        })
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(os.environ["OPENAI_COMPATIBLE_API_KEY"], "sk-new-key-5678")
        self.assertEqual(os.environ["OPENAI_COMPATIBLE_BASE_URL"], "https://new.example.com/v1")
        self.assertEqual(os.environ["OPENAI_COMPATIBLE_MODEL"], "new-model")

    def test_post_config_persists_to_env_file(self):
        """POST 后,.env 文件被更新(重启后 load_dotenv 能读到新值)。"""
        self.client.post("/api/config", json={
            "api_key": "sk-persisted-9999",
            "base_url": "https://persisted.example.com/v1",
            "model": "persisted-model",
        })
        with open(self._tmp_env, "r", encoding="utf-8") as f:
            content = f.read()
        self.assertIn("OPENAI_COMPATIBLE_API_KEY=sk-persisted-9999", content)
        self.assertIn("OPENAI_COMPATIBLE_BASE_URL=https://persisted.example.com/v1", content)
        self.assertIn("OPENAI_COMPATIBLE_MODEL=persisted-model", content)
        # 旧值应被替换,不再出现
        self.assertNotIn("sk-old-key-1234", content)

    def test_post_config_partial_update(self):
        """只传 base_url 时,api_key 和 model 保留原值。"""
        # 先设 os.environ 为已知值
        os.environ["OPENAI_COMPATIBLE_API_KEY"] = "sk-keep-this"
        os.environ["OPENAI_COMPATIBLE_MODEL"] = "keep-model"
        resp = self.client.post("/api/config", json={
            "base_url": "https://only-base.example.com/v1",
        })
        self.assertEqual(resp.status_code, 200)
        # api_key / model 未被改
        self.assertEqual(os.environ["OPENAI_COMPATIBLE_API_KEY"], "sk-keep-this")
        self.assertEqual(os.environ["OPENAI_COMPATIBLE_MODEL"], "keep-model")
        # base_url 被改
        self.assertEqual(os.environ["OPENAI_COMPATIBLE_BASE_URL"],
                         "https://only-base.example.com/v1")

    def test_post_config_masks_in_response(self):
        """POST 返回的 api_key 是脱敏的,不含完整明文。"""
        resp = self.client.post("/api/config", json={
            "api_key": "sk-supersecret-key-1234",
            "base_url": "https://resp.example.com/v1",
            "model": "resp-model",
        })
        self.assertEqual(resp.status_code, 200)
        data = resp.json()
        self.assertNotIn("supersecret", data["api_key"])
        self.assertIn("***", data["api_key"])
        # base_url / model 原样
        self.assertEqual(data["base_url"], "https://resp.example.com/v1")
        self.assertEqual(data["model"], "resp-model")


class TestTestApiConfigConnectivity(unittest.TestCase):
    """POST /api/config/test:测试当前 API 配置的连通性。

    端点用当前 os.environ 的配置构造 ChatOpenAI,发一个最小请求,
    返回 {ok: bool, message/error: str}。测试用 patch ChatOpenAI 隔离真实网络。
    """

    def setUp(self):
        from backend import server
        from fastapi.testclient import TestClient
        self.server = server
        self.client = TestClient(server.app)

    def tearDown(self):
        for k in ("OPENAI_COMPATIBLE_API_KEY", "OPENAI_COMPATIBLE_BASE_URL",
                  "OPENAI_COMPATIBLE_MODEL"):
            os.environ.pop(k, None)

    def test_connectivity_success(self):
        """配置有效且 API 响应正常时,返回 ok=True。"""
        os.environ["OPENAI_COMPATIBLE_API_KEY"] = "sk-valid"
        os.environ["OPENAI_COMPATIBLE_BASE_URL"] = "https://valid.example.com/v1"
        os.environ["OPENAI_COMPATIBLE_MODEL"] = "valid-model"

        # mock ChatOpenAI 的 ainvoke 返回成功
        async def fake_ainvoke(*args, **kwargs):
            class FakeMsg:
                content = "pong"
            return FakeMsg()

        fake_llm = MagicMock()
        fake_llm.ainvoke = fake_ainvoke
        with patch("backend.server.ChatOpenAI", return_value=fake_llm):
            resp = self.client.post("/api/config/test")
        self.assertEqual(resp.status_code, 200)
        data = resp.json()
        self.assertTrue(data["ok"])
        self.assertIn("message", data)

    def test_connectivity_missing_config(self):
        """配置缺失时,返回 ok=False 并提示缺失。"""
        for k in ("OPENAI_COMPATIBLE_API_KEY", "OPENAI_COMPATIBLE_BASE_URL",
                  "OPENAI_COMPATIBLE_MODEL"):
            os.environ.pop(k, None)
        resp = self.client.post("/api/config/test")
        self.assertEqual(resp.status_code, 200)
        data = resp.json()
        self.assertFalse(data["ok"])
        self.assertIn("error", data)

    def test_connectivity_api_failure(self):
        """API 调用失败(如 key 无效)时,返回 ok=False 并带回错误信息。"""
        os.environ["OPENAI_COMPATIBLE_API_KEY"] = "sk-invalid"
        os.environ["OPENAI_COMPATIBLE_BASE_URL"] = "https://invalid.example.com/v1"
        os.environ["OPENAI_COMPATIBLE_MODEL"] = "bad-model"

        fake_llm = MagicMock()
        fake_llm.ainvoke = AsyncMock(side_effect=Exception("401 Unauthorized"))
        with patch("backend.server.ChatOpenAI", return_value=fake_llm):
            resp = self.client.post("/api/config/test")
        self.assertEqual(resp.status_code, 200)
        data = resp.json()
        self.assertFalse(data["ok"])
        self.assertIn("error", data)
        self.assertIn("401", data["error"])


if __name__ == "__main__":
    unittest.main()
