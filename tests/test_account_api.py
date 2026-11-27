import hashlib
import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import AsyncMock, patch
from uuid import uuid4

import psycopg
from fastapi.testclient import TestClient
from psycopg import sql
from psycopg.conninfo import make_conninfo

from backend import server


BASE_URL = "http://localhost"
ORIGIN = {"Origin": BASE_URL}


def client():
    return TestClient(server.app, base_url=BASE_URL, client=("127.0.0.1", 50100))


class TestAnonymousAccess(unittest.TestCase):
    def test_private_routes_require_a_session_and_disable_caching(self):
        with client() as browser:
            for method, path, kwargs in (
                ("POST", "/api/analyze", {"json": {"query": "600519"}}),
                ("GET", "/api/status/missing", {}),
                ("GET", "/api/history", {}),
                ("GET", "/api/session", {}),
            ):
                with self.subTest(path=path):
                    response = browser.request(method, path, headers=ORIGIN, **kwargs)
                    self.assertEqual(response.status_code, 401)
                    self.assertEqual(response.headers["Cache-Control"], "no-store")

    def test_public_contract_excludes_internal_result_fields(self):
        schema = server.app.openapi()
        for path, method, model in (
            ("/api/analyze", "post", "AnalysisCreated"),
            ("/api/status/{analysis_id}", "get", "AnalysisStatusResponse"),
            ("/api/analysis/{analysis_id}/partial", "get", "AnalysisPartial"),
            ("/api/analysis/{analysis_id}/retry/{agent_key}", "post", "AnalysisRetry"),
            ("/api/result/{analysis_id}", "get", "AnalysisReport"),
            ("/api/history", "get", "AnalysisHistory"),
            ("/api/market-kline", "get", "IndexMarketResponse"),
            ("/api/stock-market", "get", "StockMarketResponse"),
        ):
            with self.subTest(path=path):
                operation = schema["paths"][path][method]
                status = "202" if model == "AnalysisRetry" else "200"
                self.assertIn(model, str(operation["responses"][status]["content"]["application/json"]["schema"]))
        report = schema["components"]["schemas"]["AnalysisReport"]["properties"]
        self.assertFalse({"report_path", "pdf_path", "api_key"} & report.keys())

    def test_validation_response_keeps_submitted_credentials_private(self):
        with client() as browser:
            response = browser.post("/api/session", headers=ORIGIN, json={"password": "private-input"})
        self.assertEqual(response.status_code, 422)
        self.assertNotIn("private-input", response.text)
        self.assertEqual(response.headers["Cache-Control"], "no-store")


@unittest.skipUnless(os.getenv("FINEX_TEST_DATABASE_URL"), "Requires FINEX_TEST_DATABASE_URL")
class TestPostgresAccounts(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        from backend.accounts import create_user, migrate

        database_url = os.environ["FINEX_TEST_DATABASE_URL"]
        schema = f"finex_test_{uuid4().hex}"
        with psycopg.connect(database_url) as conn:
            conn.execute(sql.SQL("CREATE SCHEMA {}").format(sql.Identifier(schema)))

        def drop_schema():
            with psycopg.connect(database_url) as conn:
                conn.execute(sql.SQL("DROP SCHEMA {} CASCADE").format(sql.Identifier(schema)))

        cls.addClassCleanup(drop_schema)
        cls.database_url = make_conninfo(database_url, options=f"-c search_path={schema}")
        store_env = patch.dict(os.environ, {"DATABASE_URL": cls.database_url})
        store_env.start()
        cls.addClassCleanup(store_env.stop)
        migrate(cls.database_url)
        migrate(cls.database_url)
        create_user(cls.database_url, "alice", "alice-example-password")
        create_user(cls.database_url, "bob", "bob-example-password")

    def setUp(self):
        server.analysis_sessions.clear()
        self.addCleanup(server.analysis_sessions.clear)
        overrides = patch.dict(server.app.dependency_overrides, {server.get_task_store: lambda: None})
        overrides.start()
        self.addCleanup(overrides.stop)
        self.alice = client()
        self.bob = client()
        self.addCleanup(self.alice.close)
        self.addCleanup(self.bob.close)

    def login(self, browser, username):
        response = browser.post("/api/session", headers=ORIGIN, json={
            "username": username, "password": f"{username}-example-password",
        })
        self.assertEqual(response.status_code, 200, response.text)
        self.assertIn("HttpOnly", response.headers["Set-Cookie"])
        self.assertIn("SameSite=lax", response.headers["Set-Cookie"])
        self.assertEqual(response.headers["Cache-Control"], "no-store")
        self.assertEqual(response.json()["username"], username)
        return {**ORIGIN, "X-CSRF-Token": response.json()["csrf_token"]}

    def test_invalid_credentials_and_foreign_origin_cannot_log_in(self):
        credentials = {"username": "alice", "password": "alice-example-password"}
        response = self.alice.post("/api/session", headers={"Origin": "http://foreign.test"}, json=credentials)
        self.assertEqual(response.status_code, 403)
        response = self.alice.post("/api/session", headers=ORIGIN, json={**credentials, "password": "wrong"})
        self.assertEqual(response.status_code, 401)
        self.assertEqual(self.alice.get("/api/session").status_code, 401)

    def test_https_sets_secure_cookie_and_remote_http_cannot_log_in(self):
        credentials = {"username": "alice", "password": "alice-example-password"}
        for origin, expected_status in (("https://finex.test", 200), ("http://finex.test", 403)):
            with self.subTest(origin=origin), TestClient(
                server.app, base_url=origin, client=("192.168.1.20", 50100),
            ) as browser:
                response = browser.post("/api/session", headers={"Origin": origin}, json=credentials)
                self.assertEqual(response.status_code, expected_status)
                if expected_status == 200:
                    self.assertIn("; Secure", response.headers["Set-Cookie"])
                    self.assertEqual(browser.get("/api/session").status_code, 200)

    def test_logout_revokes_only_current_session_and_expired_sessions_are_rejected(self):
        headers = self.login(self.alice, "alice")
        other_headers = self.login(self.bob, "alice")
        cookie = self.alice.cookies.get("finex_session")
        with psycopg.connect(self.database_url) as conn:
            stored_token = conn.execute(
                "SELECT token_hash FROM sessions WHERE token_hash = %s",
                (hashlib.sha256(cookie.encode()).hexdigest(),),
            ).fetchone()
            self.assertIsNotNone(stored_token)
            self.assertFalse(conn.execute("SELECT 1 FROM sessions WHERE token_hash = %s", (cookie,)).fetchone())
        self.assertEqual(self.alice.get("/api/session").status_code, 200)
        self.assertEqual(self.alice.delete("/api/session", headers=ORIGIN).status_code, 403)
        self.assertEqual(self.alice.delete("/api/session", headers=headers).status_code, 204)
        self.alice.cookies.set("finex_session", cookie)
        self.assertEqual(self.alice.get("/api/session").status_code, 401)
        self.assertEqual(self.bob.get("/api/session").json()["csrf_token"], other_headers["X-CSRF-Token"])
        with psycopg.connect(self.database_url) as conn:
            conn.execute("UPDATE sessions SET expires_at = now() - interval '1 second'")
        self.assertEqual(self.bob.get("/api/session").status_code, 401)

    def test_owner_only_routes_and_history_filter_before_limit(self):
        alice_headers = self.login(self.alice, "alice")
        bob_headers = self.login(self.bob, "bob")
        self.assertEqual(self.alice.post("/api/analyze", headers=ORIGIN, json={"query": "600519"}).status_code, 403)
        with patch.object(server, "run_analysis_workflow", new=AsyncMock()):
            created = self.alice.post("/api/analyze", headers=alice_headers, json={"query": "600519"})
            self.assertEqual(created.status_code, 200, created.text)
            task_id = created.json()["analysis_id"]
            for _ in range(11):
                response = self.bob.post("/api/analyze", headers=bob_headers, json={"query": "600900"})
                self.assertEqual(response.status_code, 200)

        self.assertEqual([item["analysis_id"] for item in self.alice.get("/api/history").json()["history"]], [task_id])
        bob_history = self.bob.get("/api/history").json()["history"]
        self.assertEqual(len(bob_history), 10)
        self.assertNotIn(task_id, [item["analysis_id"] for item in bob_history])

        task = server.analysis_sessions[task_id]
        task.status = "degraded"
        task.agent_details["news"]["status"] = "failed"
        with tempfile.TemporaryDirectory() as directory:
            report = Path(directory) / "private.md"
            report.with_suffix(".pdf").write_bytes(b"%PDF-1.7\n")
            task.result = {"report_path": str(report), "pdf_path": "private.pdf", "final_report": "# Alice"}
            task.partial_results = {"final_report": "# Alice", "pdf_path": "private.pdf"}
            routes = (
                f"/api/status/{task_id}", f"/api/analysis/{task_id}/partial",
                f"/api/result/{task_id}", f"/api/report-pdf/{task_id}",
            )
            for path in routes:
                with self.subTest(path=path):
                    response = self.bob.get(path)
                    self.assertEqual(response.status_code, 404)
                    self.assertEqual(response.json(), self.bob.get(path.replace(task_id, "missing")).json())
                    owned = self.alice.get(path)
                    self.assertEqual(owned.status_code, 200)
                    self.assertEqual(owned.headers["Cache-Control"], "no-store")
                    self.assertNotIn("private.pdf", owned.text)
            retry = f"/api/analysis/{task_id}/retry/news"
            self.assertEqual(self.bob.post(retry, headers=bob_headers).status_code, 404)
            self.assertEqual(self.bob.delete(f"/api/history/{task_id}", headers=bob_headers).status_code, 404)
            with patch.object(server, "retry_agent_and_summary", new=AsyncMock()):
                self.assertEqual(self.alice.post(retry, headers=alice_headers).status_code, 202)
