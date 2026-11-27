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
import asyncio
import os
import sys
import tempfile
import unittest
from unittest.mock import patch, MagicMock, AsyncMock
from uuid import uuid4

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
        self.client = TestClient(server.app, base_url="http://localhost", client=("127.0.0.1", 50000))

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
        self.client = TestClient(server.app, base_url="http://localhost", client=("127.0.0.1", 50000))
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

    def test_profiles_preserve_legacy_a_and_activation(self):
        legacy = {
            "OPENAI_COMPATIBLE_API_KEY": "sk-legacy-private",
            "OPENAI_COMPATIBLE_BASE_URL": "https://legacy.example/v1",
            "OPENAI_COMPATIBLE_MODEL": "legacy-model",
        }
        with patch.dict(os.environ, legacy):
            before = self.client.get("/api/config/profiles").json()
            self.assertEqual(before["active_profile"], "A")
            self.assertEqual(set(before["profiles"]), set("ABCDE"))
            self.assertEqual(before["profiles"]["A"]["model"], "legacy-model")
            self.assertEqual(self.client.put("/api/config/profiles/B?activate=true", json={}).status_code, 422)

            alternate = {"api_key": "sk-alternate-private", "base_url": "https://b.example/v1", "model": "b-model"}
            saved = self.client.put("/api/config/profiles/B", json=alternate)
            self.assertEqual(saved.status_code, 200)
            self.assertNotIn(alternate["api_key"], saved.text)
            self.assertEqual(os.environ["OPENAI_COMPATIBLE_MODEL"], "legacy-model")
            self.assertEqual(self.client.put("/api/config/profiles/F", json=alternate).status_code, 422)

            with patch.object(self.server, "ChatOpenAI") as llm:
                llm.return_value.ainvoke = AsyncMock(return_value=MagicMock(content="ok"))
                llm.return_value.bind_tools.return_value.ainvoke = AsyncMock(return_value=MagicMock(tool_calls=[{"name": "finex_connectivity_probe", "args": {"value": "ok"}, "id": "1"}]))
                check = self.client.post("/api/config/profiles/B/test", json={"model": "b-preview"})
                self.assertTrue(check.json()["ok"])
                self.assertEqual(llm.call_args.kwargs["api_key"], alternate["api_key"])
                self.assertEqual(llm.call_args.kwargs["model"], "b-preview")
                self.assertEqual(self.client.post("/api/config/profiles/B/test", json={
                    "base_url": "https://other.example/v1"
                }).status_code, 422)
                self.assertEqual(llm.call_count, 1)

            self.assertEqual(self.client.put("/api/config/profiles/B?activate=true", json={}).status_code, 200)
            self.assertEqual(os.environ["OPENAI_COMPATIBLE_MODEL"], "b-model")
            self.assertEqual(self.client.get("/api/config").json()["model"], "b-model")
            from dotenv import dotenv_values
            persisted = dotenv_values(self._tmp_env)
            self.assertEqual(persisted["FINEX_API_ACTIVE_PROFILE"], "B")
            self.assertEqual(persisted["OPENAI_COMPATIBLE_API_KEY"], alternate["api_key"])
            self.assertEqual(self.client.put("/api/config/profiles/A?activate=true", json={}).status_code, 200)
            self.assertEqual(os.environ["OPENAI_COMPATIBLE_API_KEY"], legacy["OPENAI_COMPATIBLE_API_KEY"])

    def test_profile_key_remains_identifiable_after_switching(self):
        with patch.dict(os.environ, {}, clear=True):
            a = {"api_key": "sk-first-key-1234", "base_url": "https://a.example/v1", "model": "a"}
            b = {"api_key": "sk-second-key-5678", "base_url": "https://b.example/v1", "model": "b"}
            self.assertEqual(self.client.put('/api/config/profiles/A', json=a).status_code, 200)
            self.assertEqual(self.client.put('/api/config/profiles/B?activate=true', json=b).status_code, 200)
            response = self.client.get('/api/config/profiles')
            self.assertEqual(response.json()['profiles']['A']['masked_api_key'], 'sk-***1234')
            self.assertEqual(response.json()['profiles']['B']['masked_api_key'], 'sk-***5678')
            self.assertNotIn(a['api_key'], response.text)
            self.assertEqual(self.client.put('/api/config/profiles/A?activate=true', json={'model': 'updated'}).status_code, 200)
            self.assertEqual(os.environ['OPENAI_COMPATIBLE_API_KEY'], a['api_key'])

    def test_running_analysis_keeps_original_provider_when_profile_changes(self):
        from src.utils.api_settings import current_api_settings

        principal = self.server.ActiveSession(uuid4(), "fixture", "offline-session")

        async def scenario():
            entered = asyncio.Event()
            switched = asyncio.Event()
            done = asyncio.Event()
            seen = {}

            async def analyze(analysis_id, query):
                snapshot = current_api_settings()
                if query == "600900":
                    entered.set()
                    await switched.wait()
                seen[query] = (snapshot.model, current_api_settings().model)
                if len(seen) == 2:
                    done.set()

            a = self.server.ApiConfigRequest(
                api_key="a-key", base_url="https://a.example/v1", model="a-model")
            b = self.server.ApiConfigRequest(
                api_key="b-key", base_url="https://b.example/v1", model="b-model")
            with patch.object(self.server, "run_analysis_workflow", side_effect=analyze):
                await self.server.save_api_profile("A", a, activate=True)
                await self.server.start_analysis(self.server.AnalyzeRequest(query="600900"), principal)
                await asyncio.wait_for(entered.wait(), timeout=2)
                await self.server.save_api_profile("B", b, activate=True)
                await self.server.start_analysis(self.server.AnalyzeRequest(query="600900 B"), principal)
                switched.set()
                await asyncio.wait_for(done.wait(), timeout=2)
            self.assertEqual(seen, {"600900": ("a-model", "a-model"), "600900 B": ("b-model", "b-model")})
            self.assertEqual([session.api_profile for session in self.server.analysis_sessions.values()], ["A", "B"])

        with patch.dict(os.environ), patch.object(self.server, "analysis_sessions", {}):
            asyncio.run(scenario())

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
        # 同一服务的部分更新保留已有密钥。
        os.environ["OPENAI_COMPATIBLE_API_KEY"] = "sk-keep-this"
        os.environ["OPENAI_COMPATIBLE_BASE_URL"] = "https://only-base.example.com/v1"
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
        self.client = TestClient(server.app, base_url="http://localhost", client=("127.0.0.1", 50000))

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
        fake_llm.bind_tools.return_value.ainvoke = AsyncMock(return_value=MagicMock(tool_calls=[{"name": "finex_connectivity_probe", "args": {"value": "ok"}, "id": "1"}]))
        with patch("backend.server.ChatOpenAI", return_value=fake_llm):
            resp = self.client.post("/api/config/test")
        self.assertEqual(resp.status_code, 200)
        data = resp.json()
        self.assertTrue(data["ok"])
        self.assertIn("message", data)
        self.assertEqual(data["checks"]["chat"]["status"], "passed")
        self.assertEqual(data["checks"]["tools"]["status"], "passed")

    def test_tool_failure_preserves_chat_success(self):
        os.environ.update(OPENAI_COMPATIBLE_API_KEY="sk-valid", OPENAI_COMPATIBLE_BASE_URL="https://valid.example/v1", OPENAI_COMPATIBLE_MODEL="model")
        fake = MagicMock()
        fake.ainvoke = AsyncMock(return_value=MagicMock(content="pong"))
        fake.bind_tools.return_value.ainvoke = AsyncMock(return_value=MagicMock(tool_calls=[]))
        with patch("backend.server.ChatOpenAI", return_value=fake):
            data = self.client.post('/api/config/test').json()
        self.assertFalse(data['ok'])
        self.assertEqual(data['checks']['chat']['status'], 'passed')
        self.assertEqual(data['checks']['tools']['status'], 'failed')

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
        self.assertEqual(data['checks']['chat']['status'], 'failed')
        self.assertEqual(data['checks']['tools']['status'], 'skipped')


class TestConfigAccess(unittest.TestCase):
    def test_config_routes_reject_remote_clients_and_foreign_origins(self):
        from backend import server
        from fastapi.testclient import TestClient

        for client_host, base_url, headers in [
            ("192.0.2.1", "http://localhost", {}),
            ("127.0.0.1", "http://localhost", {"Origin": "https://untrusted.example"}),
            ("127.0.0.1", "http://untrusted.example", {}),
        ]:
            client = TestClient(server.app, base_url=base_url, client=(client_host, 50000))
            for method, path in [
                ("GET", "/api/config"), ("POST", "/api/config"), ("POST", "/api/config/test"),
                ("GET", "/api/config/profiles"), ("PUT", "/api/config/profiles/B?activate=true"),
                ("POST", "/api/config/profiles/B/test"),
            ]:
                with self.subTest(client_host=client_host, base_url=base_url, path=path, method=method):
                    with patch.object(server, "update_env_file") as persist, patch.object(server, "ChatOpenAI") as llm:
                        response = client.request(method, path, headers=headers, json={"model": "new-model"})
                    self.assertEqual(response.status_code, 403)
                    persist.assert_not_called()
                    llm.assert_not_called()

    def test_changing_destination_requires_explicit_key_before_save_or_test(self):
        from backend import server
        from fastapi.testclient import TestClient

        client = TestClient(server.app, base_url="http://localhost", client=("127.0.0.1", 50000))
        settings = {"OPENAI_COMPATIBLE_API_KEY": "sk-saved", "OPENAI_COMPATIBLE_BASE_URL": "https://saved.example/v1", "OPENAI_COMPATIBLE_MODEL": "model"}
        with patch.dict(os.environ, settings):
            for path in ("/api/config", "/api/config/test"):
                with self.subTest(path=path):
                    with patch.object(server, "update_env_file") as persist, patch.object(server, "ChatOpenAI") as llm:
                        response = client.post(path, json={"base_url": "https://untrusted.example/v1"})
                    self.assertEqual(response.status_code, 422)
                    self.assertEqual(os.environ["OPENAI_COMPATIBLE_BASE_URL"], "https://saved.example/v1")
                    persist.assert_not_called()
                    llm.assert_not_called()

    def test_same_origin_local_browser_can_read_config(self):
        from backend import server
        from fastapi.testclient import TestClient

        client = TestClient(server.app, base_url="http://localhost", client=("127.0.0.1", 50000))
        self.assertEqual(client.get("/api/config", headers={"Origin": "http://localhost"}).status_code, 200)


if __name__ == "__main__":
    unittest.main()
