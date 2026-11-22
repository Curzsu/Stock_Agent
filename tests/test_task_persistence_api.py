import asyncio
import os
import threading
import time
import unittest
from concurrent.futures import ThreadPoolExecutor
from contextlib import contextmanager
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest.mock import AsyncMock, patch
from uuid import uuid4

import psycopg
from cryptography.fernet import Fernet
from fastapi import HTTPException
from fastapi.testclient import TestClient
from psycopg import sql
from psycopg.conninfo import make_conninfo

from backend import server
from backend.accounts import create_user, migrate
from backend.tasks import TaskStore


ORIGIN = "http://localhost"
PASSWORD = "offline-persistence-test"


class TestPrivateReportRoot(unittest.TestCase):
    def test_report_storage_cannot_overlap_the_static_frontend(self):
        frontend = Path(__file__).resolve().parents[1] / "frontend"
        for root in (frontend.parent, frontend / "assets" / "reports", frontend / "dist" / "reports"):
            with self.subTest(root=root), self.assertRaises(ValueError):
                TaskStore("postgresql://localhost/db", root, "")


@contextmanager
def local_test_database():
    database_url = os.environ["FINEX_TEST_DATABASE_URL"]
    schema = f"finex_test_{uuid4().hex}"
    with psycopg.connect(database_url) as conn:
        conn.execute(sql.SQL("CREATE SCHEMA {}").format(sql.Identifier(schema)))
    try:
        isolated_url = make_conninfo(database_url, options=f"-c search_path={schema}")
        migrate(isolated_url)
        yield isolated_url
    finally:
        with psycopg.connect(database_url) as conn:
            conn.execute(sql.SQL("DROP SCHEMA {} CASCADE").format(sql.Identifier(schema)))


@unittest.skipUnless(os.getenv("FINEX_TEST_DATABASE_URL"), "Requires FINEX_TEST_DATABASE_URL")
class TestTaskPersistenceApi(unittest.TestCase):
    def setUp(self):
        database = local_test_database()
        self.database_url = database.__enter__()
        self.addCleanup(database.__exit__, None, None, None)
        directory = TemporaryDirectory()
        self.addCleanup(directory.cleanup)
        self.report_dir = directory.name
        settings = patch.dict(os.environ, {
            "DATABASE_URL": self.database_url,
            "FINEX_MODEL_CONFIG_KEY": Fernet.generate_key().decode(),
            "FINEX_REPORT_DIR": self.report_dir,
            "FINEX_MAX_USER_TASKS": "1",
            "FINEX_MAX_ACTIVE_TASKS": "2",
        })
        settings.start()
        self.addCleanup(settings.stop)
        for name in ("alice", "bob", "charlie"):
            create_user(self.database_url, name, PASSWORD)
        server.analysis_sessions.clear()
        self.addCleanup(server.analysis_sessions.clear)

    def browser(self, username, manager):
        browser = TestClient(server.app, base_url=ORIGIN, client=("127.0.0.1", 50000))
        browser.portal = manager.portal
        self.addCleanup(browser.close)
        login = browser.post("/api/session", headers={"Origin": ORIGIN}, json={"username": username, "password": PASSWORD})
        self.assertEqual(login.status_code, 200)
        browser.headers.update({"Origin": ORIGIN, "X-CSRF-Token": login.json()["csrf_token"]})
        return browser

    def submit(self, browser, key, query="600519"):
        return browser.post("/api/analyze", headers={"Idempotency-Key": key}, json={"query": query})

    def wait_status(self, browser, task_id, expected):
        deadline = time.monotonic() + 8
        while time.monotonic() < deadline:
            response = browser.get(f"/api/status/{task_id}")
            self.assertEqual(response.status_code, 200, response.text)
            if response.json()["status"] == expected:
                return response.json()
            time.sleep(0.025)
        self.fail(f"Expected {expected}, got {response.json()['status']}")

    def test_concurrent_duplicate_reserves_one_task_and_limits_both_owners(self):
        with TestClient(server.app, base_url=ORIGIN, client=("127.0.0.1", 50000)) as manager:
            alice = self.browser("alice", manager)
            bob = self.browser("bob", manager)
            charlie = self.browser("charlie", manager)
            barrier = threading.Barrier(2)

            async def hold_task(*_args):
                await asyncio.Event().wait()

            def submit_twice():
                barrier.wait(5)
                return self.submit(alice, "alice-first")

            with patch.object(server, "run_analysis_workflow", AsyncMock(side_effect=hold_task)):
                with ThreadPoolExecutor(max_workers=2) as pool:
                    futures = [pool.submit(submit_twice) for _ in range(2)]
                    responses = [future.result(timeout=15) for future in futures]
                self.assertEqual([response.status_code for response in responses], [200, 200])
                self.assertEqual(responses[0].json()["analysis_id"], responses[1].json()["analysis_id"])
                self.assertEqual(self.submit(alice, "alice-first", "600900").status_code, 409)
                self.assertEqual(self.submit(alice, "alice-second").status_code, 429)
                self.assertEqual(self.submit(bob, "alice-first").status_code, 200)
                self.assertEqual(self.submit(charlie, "charlie-first").status_code, 429)
                self.assertEqual(server.run_analysis_workflow.await_count, 2)
                self.assertEqual(manager.get("/api/health").status_code, 200)

    def test_restart_recovers_partials_keeps_pdf_and_retries_original_configuration(self):
        async def complete(task_id, query):
            task = server.analysis_sessions[task_id]
            task.initial_data = {"stock_code": "sh.600519", "query": query}
            server.record_agent_result(task, "fundamental", {"data": {"fundamental_analysis": "# 保留的片段"}})
            if query == "600900":
                task.status = "running"
                server.mark_agent_status(task, "news", "running")
                await server.checkpoint_analysis(task)
                await asyncio.Event().wait()
            self.write_report(task, "first")

        old_key = "previous-provider-key"
        with patch.dict(os.environ, {"OPENAI_COMPATIBLE_API_KEY": old_key, "OPENAI_COMPATIBLE_MODEL": "model-original"}), \
                patch.object(server, "run_analysis_workflow", AsyncMock(side_effect=complete)), \
                TestClient(server.app, base_url=ORIGIN, client=("127.0.0.1", 50000)) as manager:
            alice = self.browser("alice", manager)
            report_id = self.submit(alice, "report-a").json()["analysis_id"]
            self.wait_status(alice, report_id, "degraded")
            active_id = self.submit(alice, "active-a", "600900").json()["analysis_id"]
            self.wait_status(alice, active_id, "running")

        with psycopg.connect(self.database_url) as conn:
            original_doc_id, version, state = conn.execute(
                "SELECT document_id, content_version, pdf_status FROM report_documents WHERE task_id = %s", (report_id,),
            ).fetchone()
            self.assertEqual((version, state), (1, "ready"))
            ciphertext, snapshot = conn.execute(
                """SELECT ciphertext, snapshot FROM analysis_tasks JOIN model_config_versions
                   ON config_version_id = model_config_versions.id WHERE analysis_tasks.id = %s""", (report_id,),
            ).fetchone()
            self.assertNotIn(old_key.encode(), ciphertext)
            self.assertNotIn(old_key, str(snapshot))

        async def retry(task_id, agent):
            self.assertEqual(server.current_api_settings().api_key, old_key)
            self.assertEqual(server.current_api_settings().model, "model-original")
            self.assertEqual(server.current_summary_mode(), "api")
            self.assertEqual(agent, "news")
            self.write_report(server.analysis_sessions[task_id], "second")

        with patch.dict(os.environ, {"OPENAI_COMPATIBLE_API_KEY": "different-key", "OPENAI_COMPATIBLE_MODEL": "new-model",
                                     "USE_LOCAL_MODEL": "local"}), \
                patch.object(server, "retry_agent_and_summary", AsyncMock(side_effect=retry)) as retried, \
                TestClient(server.app, base_url=ORIGIN, client=("127.0.0.1", 50000)) as manager:
            alice = self.browser("alice", manager)
            bob = self.browser("bob", manager)
            self.assertEqual(alice.get(f"/api/status/{active_id}").json()["status"], "interrupted")
            self.assertEqual([item["analysis_id"] for item in alice.get("/api/history").json()["history"]], [report_id, active_id])
            self.assertEqual(bob.get("/api/history").json()["history"], [])
            self.assertEqual(alice.get(f"/api/analysis/{active_id}/partial").json()["results"],
                             {"fundamental_analysis": "# 保留的片段"})
            self.assertEqual(self.submit(alice, "active-a", "600900").json()["analysis_id"], active_id)
            self.assertEqual(bob.get(f"/api/result/{report_id}").status_code, 404)
            self.assertEqual(bob.get(f"/api/report-pdf/{report_id}").status_code, 404)
            self.assertEqual(alice.get(f"/api/report-pdf/{report_id}").content, b"%PDF-1.7\nfirst")
            self.assertEqual(alice.get(f"/api/result/{report_id}").json()["final_report"], "# first")
            self.assertEqual(alice.post(f"/api/analysis/{report_id}/retry/news").status_code, 202)
            self.wait_status(alice, report_id, "degraded")
            self.assertEqual(alice.get(f"/api/report-pdf/{report_id}").content, b"%PDF-1.7\nsecond")
            with psycopg.connect(self.database_url) as conn:
                current_doc_id, version = conn.execute(
                    "SELECT document_id, content_version FROM report_documents WHERE task_id = %s", (report_id,),
                ).fetchone()
                self.assertEqual((current_doc_id, version), (original_doc_id, 2))
                conn.execute("UPDATE model_config_versions SET revoked_at = now(), ciphertext = NULL")
            unavailable = alice.post(f"/api/analysis/{report_id}/retry/news")
            self.assertEqual(unavailable.status_code, 409)
            self.assertIn("重新提交", unavailable.json()["detail"])
            self.assertEqual(retried.await_count, 1)
            self.assertEqual(alice.delete(f"/api/history/{report_id}").status_code, 200)
            self.assertFalse((Path(self.report_dir) / report_id).exists())
            self.assertEqual(alice.get(f"/api/result/{report_id}").status_code, 404)
            self.assertEqual(self.submit(alice, "report-a").status_code, 409)

    def write_report(self, task, text):
        root = Path(server.report_metadata_for(task)["report_dir"])
        markdown = root / "md" / f"{text}.md"
        pdf = root / "pdf" / f"{text}.pdf"
        for file in (markdown, pdf):
            file.parent.mkdir(parents=True, exist_ok=True)
        markdown.write_text(f"# {text}", encoding="utf-8")
        pdf.write_bytes(b"%PDF-1.7\n" + text.encode())
        task.result = {"report_path": str(markdown), "final_report": f"# {text}",
                       "stock_code": "600519", "analysis_date": "2026-11-22"}
        task.status = "degraded"
        server.record_agent_result(task, "news", {"data": {
            "news_analysis_error": f"provider rejected {server.current_api_settings().api_key} while reading {markdown}",
        }})

    def test_failed_document_write_rolls_back_task_checkpoint(self):
        async def hold(*_args):
            await asyncio.Event().wait()

        with patch.object(server, "run_analysis_workflow", AsyncMock(side_effect=hold)), \
                TestClient(server.app, base_url=ORIGIN, client=("127.0.0.1", 50000)) as manager:
            alice = self.browser("alice", manager)
            task_id = self.submit(alice, "rollback-report").json()["analysis_id"]
            with psycopg.connect(self.database_url) as conn:
                owner, initial_snapshot = conn.execute("SELECT owner_id, snapshot FROM analysis_tasks WHERE id = %s",
                                                       (task_id,)).fetchone()
            store = server.app.state.task_store
            bad_report = ("600519", "invalid-date", f"{task_id}/md/report.md", f"{task_id}/pdf/report.pdf", "ready")
            with self.assertRaises(HTTPException) as rejected:
                store.checkpoint(task_id, owner, "completed", {**initial_snapshot, "error": "new"}, bad_report)
            self.assertEqual(rejected.exception.status_code, 500)
            with psycopg.connect(self.database_url) as conn:
                stored = conn.execute("SELECT status, snapshot FROM analysis_tasks WHERE id = %s", (task_id,)).fetchone()
                self.assertEqual(stored, ("pending", initial_snapshot))
                self.assertIsNone(conn.execute("SELECT 1 FROM report_documents WHERE task_id = %s", (task_id,)).fetchone())

    def test_pdf_state_updates_without_download_and_retry_uses_same_capacity(self):
        from src.utils import pdf_converter

        release = threading.Event()

        async def render(markdown, _state):
            if await asyncio.to_thread(release.wait, 12):
                Path(pdf_converter.derive_pdf_path(markdown)).write_bytes(b"%PDF-1.7\nfinished")

        async def complete(task_id, query):
            if query == "600900":
                await asyncio.Event().wait()
            task = server.analysis_sessions[task_id]
            self.write_report(task, "pending")
            markdown = task.result["report_path"]
            Path(pdf_converter.derive_pdf_path(markdown)).unlink()
            pdf_converter.start_pdf_generation(markdown, {})

        with patch.object(server, "run_analysis_workflow", AsyncMock(side_effect=complete)), \
                patch.object(pdf_converter, "generate_pdf_background", render), \
                TestClient(server.app, base_url=ORIGIN, client=("127.0.0.1", 50000)) as manager:
            alice = self.browser("alice", manager)
            try:
                report_id = self.submit(alice, "pending-pdf").json()["analysis_id"]
                self.wait_status(alice, report_id, "degraded")
                self.assertEqual(alice.get(f"/api/report-pdf/{report_id}").json()["detail"]["status"], "pending")
                self.assertEqual(self.submit(alice, "hold-user-slot", "600900").status_code, 200)
                self.assertEqual(alice.post(f"/api/analysis/{report_id}/retry/news").status_code, 429)
                release.set()
                with psycopg.connect(self.database_url, autocommit=True) as conn:
                    deadline = time.monotonic() + 5
                    while time.monotonic() < deadline:
                        if conn.execute("SELECT pdf_status FROM report_documents WHERE task_id = %s",
                                        (report_id,)).fetchone() == ("ready",):
                            break
                        time.sleep(0.05)
                    else:
                        self.fail("PDF metadata did not update after rendering")
                self.assertEqual(alice.get(f"/api/report-pdf/{report_id}").content, b"%PDF-1.7\nfinished")
            finally:
                release.set()

    def test_permanent_report_save_error_preserves_last_checkpoint_and_releases_capacity(self):
        async def produce_bad_report(task_id, query):
            task = server.analysis_sessions[task_id]
            if query == "600519":
                task.status = "running"
                server.record_agent_result(task, "fundamental", {"data": {"fundamental_analysis": "# 已保存"}})
                await server.checkpoint_analysis(task)
                self.write_report(task, "unpublishable")
                task.result["final_report"] = "Invalid PostgreSQL JSONB text\x00"
            else:
                task.status = "error"

        with patch.object(server, "run_analysis_workflow", AsyncMock(side_effect=produce_bad_report)), \
                TestClient(server.app, base_url=ORIGIN, client=("127.0.0.1", 50000)) as manager:
            alice = self.browser("alice", manager)
            task_id = self.submit(alice, "invalid-report").json()["analysis_id"]
            status = self.wait_status(alice, task_id, "error")
            self.assertIn("保存", status["error"])
            self.assertEqual(alice.get(f"/api/analysis/{task_id}/partial").json()["results"], {"fundamental_analysis": "# 已保存"})
            self.assertEqual(self.submit(alice, "slot-released", "600900").status_code, 200)

    def test_delete_commit_failure_protects_files_and_restart_retries_cleanup(self):
        async def produce(task_id, _query):
            self.write_report(server.analysis_sessions[task_id], "retained")

        with patch.object(server, "run_analysis_workflow", AsyncMock(side_effect=produce)), \
                TestClient(server.app, base_url=ORIGIN, client=("127.0.0.1", 50000)) as manager:
            alice = self.browser("alice", manager)
            task_id = self.submit(alice, "delete-recovery").json()["analysis_id"]
            self.wait_status(alice, task_id, "degraded")
            with psycopg.connect(self.database_url) as conn:
                conn.execute("""CREATE FUNCTION reject_delete() RETURNS trigger LANGUAGE plpgsql AS $$
                               BEGIN RAISE EXCEPTION 'test commit failure'; END; $$""")
                conn.execute("""CREATE CONSTRAINT TRIGGER reject_delete AFTER UPDATE ON analysis_tasks
                               DEFERRABLE INITIALLY DEFERRED FOR EACH ROW WHEN (NEW.deleted_at IS NOT NULL)
                               EXECUTE FUNCTION reject_delete()""")
            self.assertEqual(alice.delete(f"/api/history/{task_id}").status_code, 500)
            self.assertEqual(alice.get(f"/api/report-pdf/{task_id}").content, b"%PDF-1.7\nretained")
            with psycopg.connect(self.database_url) as conn:
                conn.execute("DROP TRIGGER reject_delete ON analysis_tasks")
            with patch.object(server.shutil, "rmtree", side_effect=PermissionError("fixture: in use")):
                response = alice.delete(f"/api/history/{task_id}")
            self.assertEqual(response.status_code, 500)
            self.assertEqual(alice.get(f"/api/result/{task_id}").status_code, 404)
            self.assertTrue((Path(self.report_dir) / task_id).exists())

        with TestClient(server.app, base_url=ORIGIN, client=("127.0.0.1", 50000)):
            self.assertFalse((Path(self.report_dir) / task_id).exists())

    def test_executor_from_a_previous_database_generation_cannot_admit_work(self):
        with TestClient(server.app, base_url=ORIGIN, client=("127.0.0.1", 50000)) as manager:
            alice = self.browser("alice", manager)
            with psycopg.connect(self.database_url) as conn:
                conn.execute("UPDATE task_runner SET run_id = %s", (uuid4(),))
            self.assertEqual(self.submit(alice, "obsolete-executor").status_code, 503)
            with psycopg.connect(self.database_url) as conn:
                self.assertFalse(conn.execute("SELECT 1 FROM analysis_tasks").fetchone())
