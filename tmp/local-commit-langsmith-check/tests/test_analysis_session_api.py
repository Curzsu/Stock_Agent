import os
import asyncio
import sys
import json
import tempfile
import threading
import unittest
from pathlib import Path
from unittest.mock import AsyncMock, patch

from fastapi.testclient import TestClient


PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, PROJECT_ROOT)
sys.path.insert(0, os.path.join(PROJECT_ROOT, "agents"))

from backend import server
from src.utils import pdf_converter


class TestAnalysisSessionApi(unittest.TestCase):
    def setUp(self):
        server.analysis_sessions.clear()
        self.client = TestClient(server.app, base_url="http://localhost", client=("127.0.0.1", 50000))
        self.session = server.AnalysisStatus(
            analysis_id="session1",
            status="running",
            progress={
                "fundamental": "completed",
                "technical": "running",
                "value": "waiting",
                "news": "waiting",
                "summary": "waiting",
            },
            agent_details=server.new_agent_details(),
            partial_results={"fundamental_analysis": "# 基本面\n\n盈利能力保持稳健。"},
        )
        self.session.agent_details["fundamental"].update({
            "status": "completed",
            "summary": "盈利能力保持稳健。",
            "result_available": True,
            "execution_time_ms": 48000,
        })
        self.session.initial_data = {"stock_code": "sh.600519"}
        server.analysis_sessions["session1"] = self.session

    def tearDown(self):
        server.analysis_sessions.clear()

    def test_status_includes_agent_details_and_current_task(self):
        response = self.client.get("/api/status/session1")
        self.assertEqual(response.status_code, 200)
        payload = response.json()
        self.assertEqual(
            payload["agent_details"]["fundamental"]["summary"],
            "盈利能力保持稳健。",
        )
        self.assertIn("current_task", payload)
        self.assertEqual(payload["stock_code"], "sh.600519")

    def test_partial_endpoint_returns_only_completed_results(self):
        response = self.client.get("/api/analysis/session1/partial")
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()["results"], {
            "fundamental_analysis": "# 基本面\n\n盈利能力保持稳健。",
        })

    def test_pdf_failure_is_terminal_instead_of_pending_forever(self):
        with tempfile.TemporaryDirectory() as directory:
            report = Path(directory) / "report.md"
            self.session.status = "completed"
            self.session.result = {"report_path": str(report)}
            report.with_suffix(".pdf.status.json").write_text(
                json.dumps({"status": "failed", "message": "缺少 XeLaTeX/Tectonic"}), encoding="utf-8",
            )
            response = self.client.get("/api/report-pdf/session1")
        self.assertEqual(response.status_code, 500)
        self.assertEqual(response.json()["detail"]["status"], "failed")
        self.assertIn("Tectonic", response.json()["detail"]["message"])

    def test_pdf_pending_and_success_keep_existing_download_contract(self):
        with tempfile.TemporaryDirectory() as directory:
            report = Path(directory) / "report.md"
            self.session.status = "completed"
            self.session.result = {"report_path": str(report), "company_name": "示例公司"}
            pending = self.client.get("/api/report-pdf/session1")
            self.assertEqual(pending.status_code, 404)
            self.assertEqual(pending.json()["detail"]["status"], "pending")
            content = b"%PDF-1.7\ncomplete report\n%%EOF\n"
            report.with_suffix(".pdf").write_bytes(content)
            ready = self.client.get("/api/report-pdf/session1")
            self.assertEqual(ready.status_code, 200)
            self.assertEqual(ready.content, content)
            self.assertEqual(ready.headers["content-type"], "application/pdf")

    def test_invalid_agent_result_is_failed_instead_of_completed(self):
        for agent_key, (result_key, _) in server.AGENT_RESULT_KEYS.items():
            for content in (None, "", " \n ", "No analysis generated.", {"unexpected": "data"}):
                with self.subTest(agent=agent_key, content=content):
                    self.session.partial_results[result_key] = "旧结果"
                    server.record_agent_result(self.session, agent_key, {"data": {result_key: content}})
                    detail = self.session.agent_details[agent_key]
                    self.assertEqual(detail["status"], "failed")
                    self.assertEqual(self.session.progress[agent_key], "failed")
                    self.assertFalse(detail["result_available"])
                    self.assertTrue(detail["error"])
                    self.assertNotIn(result_key, self.session.partial_results)

    def test_summary_uses_first_non_heading_paragraph(self):
        text = "# 标题\n\n**结论**\n\n盈利能力保持稳健，现金流良好。\n\n后续详情。"
        self.assertEqual(
            server.summarize_agent_text(text),
            "盈利能力保持稳健，现金流良好。",
        )

    def test_record_agent_result_persists_summary_and_error(self):
        now = "2026-08-10T12:00:00"
        self.session.agent_details["fundamental"]["started_at"] = now
        server.record_agent_result(
            self.session,
            "fundamental",
            {"data": {"fundamental_analysis": "# 结论\n\n盈利能力保持稳健。"}},
            completed_at=now,
        )
        detail = self.session.agent_details["fundamental"]
        self.assertEqual(detail["status"], "completed")
        self.assertTrue(detail["result_available"])
        self.assertEqual(
            self.session.partial_results["fundamental_analysis"],
            "# 结论\n\n盈利能力保持稳健。",
        )

        server.record_agent_result(
            self.session,
            "news",
            {"data": {"news_analysis_error": "新闻源不可用"}},
            completed_at=now,
        )
        self.assertEqual(self.session.agent_details["news"]["status"], "failed")
        self.assertEqual(self.session.progress["news"], "failed")

    def test_stock_market_endpoint_returns_structured_payload(self):
        payload = {
            "ok": True,
            "code": "sh.600519",
            "latest_trade_date": "2026-08-07",
            "quote": {"close": 1482.5, "pct_change": 1.28},
            "candles": [
                {
                    "time": "2026-08-06",
                    "open": 1460,
                    "high": 1480,
                    "low": 1450,
                    "close": 1470,
                    "volume": 100,
                    "ma5": None,
                    "ma20": None,
                },
                {
                    "time": "2026-08-07",
                    "open": 1470,
                    "high": 1490,
                    "low": 1462,
                    "close": 1482.5,
                    "volume": 120,
                    "ma5": None,
                    "ma20": None,
                },
            ],
        }
        with patch.object(server, "fetch_stock_market", return_value=payload):
            response = self.client.get("/api/stock-market?code=600519")
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json(), payload)

    def test_retry_accepts_only_failed_analysis_agents(self):
        self.session.agent_details["news"]["status"] = "failed"

        response = self.client.post("/api/analysis/session1/retry/news")
        self.assertEqual(response.status_code, 409)

        self.session.status = "degraded"
        with patch.object(server, "retry_agent_and_summary", new=AsyncMock()):
            response = self.client.post("/api/analysis/session1/retry/news")
        self.assertEqual(response.status_code, 202)
        self.assertEqual(response.json()["status"], "retrying")

        response = self.client.post("/api/analysis/session1/retry/fundamental")
        self.assertEqual(response.status_code, 409)

        response = self.client.post("/api/analysis/session1/retry/summary")
        self.assertEqual(response.status_code, 409)

    def test_summary_retry_reuses_partial_results(self):
        self.session.status = "error"
        self.session.error = "summary failed"
        for key in ("fundamental", "technical", "value", "news"):
            self.session.agent_details[key]["status"] = "completed"
            self.session.progress[key] = "completed"
            self.session.partial_results[server.AGENT_RESULT_KEYS[key][0]] = key + " result"
        self.session.agent_details["summary"]["status"] = "failed"
        self.session.progress["summary"] = "failed"
        before = dict(self.session.partial_results)
        with patch.object(server, "retry_agent_and_summary", new=AsyncMock()) as retry:
            response = self.client.post("/api/analysis/session1/retry/summary")
        self.assertEqual(response.status_code, 202)
        self.assertEqual(self.session.status, "running")
        self.assertIsNone(self.session.error)
        self.assertEqual(self.session.partial_results, before)

        async def summary(state):
            self.assertEqual(state["data"]["news_analysis"], "news result")
            return {"data": {"final_report": "成功汇总"}}

        analyst = AsyncMock(side_effect=AssertionError("must not rerun analyst"))
        asyncio.run(server.retry_agent_and_summary(
            "session1", "summary", selected_agent=analyst, summarizer=summary,
        ))
        analyst.assert_not_called()
        self.assertEqual(self.session.status, "completed")
        self.assertEqual(self.session.result["final_report"], "成功汇总")

    def test_retry_rejects_parallel_agent_runs(self):
        self.session.status = "degraded"
        self.session.agent_details["news"]["status"] = "failed"
        self.session.agent_details["value"]["status"] = "running"
        response = self.client.post("/api/analysis/session1/retry/news")
        self.assertEqual(response.status_code, 409)

    def test_summary_retry_rejects_incomplete_fragments_and_unknown_agents(self):
        self.session.status = "error"
        self.session.agent_details["summary"]["status"] = "failed"
        self.assertEqual(self.client.post("/api/analysis/session1/retry/summary").status_code, 409)
        self.assertEqual(self.client.post("/api/analysis/session1/retry/unknown").status_code, 422)

    def test_summary_only_retry_preserves_missing_dimension_warning(self):
        self.session.agent_details["news"].update(status="failed", error="news unavailable")
        async def summary(state):
            self.assertEqual(state["data"]["news_analysis_error"], "news unavailable")
            return {"data": {"final_report": "部分数据缺失的综合报告"}}
        asyncio.run(server.retry_agent_and_summary("session1", "summary", summarizer=summary))
        self.assertEqual(self.session.status, "degraded")
        self.assertEqual(self.session.result["missing_dimensions"], ["news"])

    def test_retry_helper_replaces_failed_dimension_and_reruns_summary(self):
        import asyncio

        self.session.status = "degraded"
        self.session.initial_data = {"query": "贵州茅台", "stock_code": "sh.600519"}
        self.session.partial_results = {"fundamental_analysis": "基本面结果"}
        self.session.agent_details["news"]["status"] = "failed"
        self.session.progress["news"] = "failed"
        summary_inputs = []

        async def fake_news(state):
            return {"data": {**state["data"], "news_analysis": "新闻重试结果"}}

        async def fake_summary(state):
            summary_inputs.append(dict(state["data"]))
            return {"data": {**state["data"], "final_report": "重建后的综合报告"}}

        asyncio.run(server.retry_agent_and_summary(
            "session1",
            "news",
            selected_agent=fake_news,
            summarizer=fake_summary,
        ))

        self.assertEqual(self.session.partial_results["fundamental_analysis"], "基本面结果")
        self.assertEqual(self.session.partial_results["news_analysis"], "新闻重试结果")
        self.assertEqual(len(summary_inputs), 1)
        self.assertEqual(summary_inputs[0]["news_analysis"], "新闻重试结果")

    def test_summary_failure_marks_initial_workflow_as_error(self):
        async def analyst(state):
            return {"data": {"fundamental_analysis": "available fragment"}}

        async def failed_summary(state):
            return {"data": {"summary_error": "model unavailable", "final_report": "error fallback"}}

        with patch.object(server, "verify_stock_code_exists", return_value=(True, "贵州茅台")), \
             patch.object(server, "fundamental_agent", analyst), \
             patch.object(server, "technical_agent", analyst), \
             patch.object(server, "value_agent", analyst), \
             patch.object(server, "news_agent", analyst), \
             patch.object(server, "summary_agent", failed_summary):
            asyncio.run(server.run_analysis_workflow("session1", "600519"))

        self.assertEqual(self.session.status, "error")
        self.assertIn("model unavailable", self.session.error)
        self.assertEqual(self.session.agent_details["summary"]["status"], "failed")
        self.assertEqual(self.session.partial_results["fundamental_analysis"], "available fragment")
        self.assertIsNotNone(self.session.end_time)
        self.assertIsNone(self.session.current_task)

    def test_summary_failure_during_retry_is_not_completed(self):
        async def recovered_news(state):
            return {"data": {"news_analysis": "recovered news"}}

        async def failed_summary(state):
            return {"data": {"summary_error": "model unavailable"}}

        asyncio.run(server.retry_agent_and_summary(
            "session1", "news", selected_agent=recovered_news, summarizer=failed_summary,
        ))

        self.assertEqual(self.session.status, "error")
        self.assertIn("model unavailable", self.session.error)
        self.assertEqual(self.session.partial_results["news_analysis"], "recovered news")

    def test_retry_exception_finishes_the_actual_failed_stage(self):
        async def recovered_news(state):
            return {"data": {"news_analysis": "recovered news"}}

        async def crash(state):
            raise RuntimeError(error_message)

        for failed_stage, error_message in (("news", "stage crashed"), ("summary", "stage crashed"), ("summary", "")):
            with self.subTest(failed_stage=failed_stage, error_message=error_message):
                self.session.agent_details = server.new_agent_details()
                for key, detail in self.session.agent_details.items():
                    detail["status"] = "completed"
                    self.session.progress[key] = "completed"
                self.session.agent_details["news"]["status"] = "failed"
                self.session.status = "degraded"
                self.session.end_time = None
                asyncio.run(server.retry_agent_and_summary(
                    "session1", "news",
                    selected_agent=crash if failed_stage == "news" else recovered_news,
                    summarizer=crash,
                ))
                self.assertFalse(any(d["status"] == "running" for d in self.session.agent_details.values()))
                self.assertEqual(self.session.agent_details[failed_stage]["status"], "failed")
                self.assertEqual(self.session.progress[failed_stage], "failed")
                self.assertIn(error_message or "RuntimeError", self.session.agent_details[failed_stage]["error"])
                self.assertIsNotNone(self.session.end_time)
                self.assertIsNone(self.session.current_task)
                if failed_stage == "summary":
                    self.assertEqual(self.session.agent_details["news"]["status"], "completed")
                    self.assertEqual(self.session.status, "error")
                else:
                    self.assertEqual(self.session.status, "degraded")

    def test_delete_completed_analysis_removes_session_and_files(self):
        with tempfile.TemporaryDirectory() as directory:
            report_file = Path(directory) / "report_test.md"
            report_file.write_text("# 研报内容", encoding="utf-8")
            pdf_file = Path(directory) / "report_test.pdf"
            pdf_file.write_bytes(b"%PDF-1.7 ...")
            status_file = pdf_file.with_suffix(".pdf.status.json")
            status_file.write_text('{"status": "ready"}', encoding="utf-8")
            log_file = pdf_file.with_suffix(".pdf.log")
            log_file.write_text("ok", encoding="utf-8")

            self.session.status = "completed"
            self.session.result = {
                "report_path": str(report_file),
                "pdf_path": str(pdf_file),
                "company_name": "测试股份",
                "stock_code": "600519",
            }

            response = self.client.delete("/api/history/session1")
            self.assertEqual(response.status_code, 200)
            self.assertEqual(response.json()["status"], "deleted")
            self.assertEqual(response.json()["analysis_id"], "session1")

            # Verify session is deleted from memory
            self.assertNotIn("session1", server.analysis_sessions)

            # Verify disk files were removed
            self.assertFalse(report_file.exists())
            self.assertFalse(pdf_file.exists())
            self.assertFalse(status_file.exists())
            self.assertFalse(log_file.exists())

    def test_delete_running_or_pending_analysis_returns_409(self):
        self.session.status = "running"
        response = self.client.delete("/api/history/session1")
        self.assertEqual(response.status_code, 409)
        self.assertIn("进行中", response.json()["detail"])
        self.assertIn("session1", server.analysis_sessions)

        self.session.status = "pending"
        response2 = self.client.delete("/api/history/session1")
        self.assertEqual(response2.status_code, 409)
        self.assertIn("session1", server.analysis_sessions)

    def test_delete_nonexistent_analysis_returns_404(self):
        response = self.client.delete("/api/history/nonexistent_id")
        self.assertEqual(response.status_code, 404)
        self.assertEqual(response.json()["detail"], "Analysis not found")

    def test_delete_removes_from_history_endpoint(self):
        self.session.status = "completed"
        self.session.result = {"company_name": "测试企业", "stock_code": "000001"}
        history_before = self.client.get("/api/history").json()["history"]
        self.assertTrue(any(item["analysis_id"] == "session1" for item in history_before))

        response = self.client.delete("/api/history/session1")
        self.assertEqual(response.status_code, 200)

        history_after = self.client.get("/api/history").json()["history"]
        self.assertFalse(any(item["analysis_id"] == "session1" for item in history_after))

    def test_delete_via_alternative_analysis_path(self):
        self.session.status = "completed"
        response = self.client.delete("/api/analysis/session1")
        self.assertEqual(response.status_code, 200)
        self.assertNotIn("session1", server.analysis_sessions)

    def test_delete_rejects_remote_clients_and_foreign_origins(self):
        self.session.status = "completed"
        for route in ("/api/history/session1", "/api/analysis/session1"):
            for host, url, origin in (
                ("192.168.1.20", "http://localhost", None),
                ("127.0.0.1", "http://localhost", "https://example.com"),
                ("127.0.0.1", "http://attacker.example", None),
            ):
                with self.subTest(route=route, host=host, origin=origin):
                    server.analysis_sessions["session1"] = self.session
                    client = TestClient(server.app, base_url=url, client=(host, 50000))
                    response = client.delete(route, headers={"Origin": origin} if origin else {})
                    self.assertEqual(response.status_code, 403)
                    self.assertIn("session1", server.analysis_sessions)

    def test_delete_accepts_same_origin_local_page(self):
        self.session.status = "completed"
        response = self.client.delete("/api/history/session1", headers={"Origin": "http://localhost"})
        self.assertEqual(response.status_code, 200)

    def test_delete_file_failure_preserves_history_for_retry(self):
        for blocked_name in ("report.pdf", "report.pdf.status.json", "report.pdf.log", "report.md"):
            with self.subTest(blocked=blocked_name), tempfile.TemporaryDirectory() as directory:
                paths = [Path(directory) / name for name in
                         ("report.pdf", "report.pdf.status.json", "report.pdf.log", "report.md")]
                for path in paths:
                    path.write_text("content", encoding="utf-8")
                self.session.status = "completed"
                self.session.result = {"report_path": str(paths[-1]), "pdf_path": str(paths[0])}
                server.analysis_sessions["session1"] = self.session
                original_unlink = Path.unlink
                def unlink(path, *args, **kwargs):
                    if path.name == blocked_name:
                        raise PermissionError("file in use")
                    return original_unlink(path, *args, **kwargs)
                # Cover both removal APIs used by the original implementation.
                original_remove = os.remove
                def remove(path, *args, **kwargs):
                    if Path(path).name == blocked_name:
                        raise PermissionError("file in use")
                    return original_remove(path, *args, **kwargs)
                with patch.object(Path, "unlink", unlink), patch.object(os, "remove", remove):
                    response = self.client.delete("/api/history/session1")
                self.assertEqual(response.status_code, 500)
                self.assertIn("session1", server.analysis_sessions)
                self.assertTrue((Path(directory) / blocked_name).exists())
                self.assertEqual(self.client.delete("/api/history/session1").status_code, 200)
                self.assertFalse(any(path.exists() for path in paths))

    def test_delete_waits_for_background_pdf_before_removing_files(self):
        async def scenario(directory):
            report = Path(directory) / "report.md"
            report.write_text("report", encoding="utf-8")
            pdf = report.with_suffix(".pdf")
            self.session.status = "completed"
            self.session.result = {"report_path": str(report)}
            entered, release = threading.Event(), threading.Event()
            def render(*args):
                entered.set()
                if not release.wait(5):
                    raise RuntimeError("test PDF worker timed out")
                pdf.write_bytes(b"%PDF-content")
                return str(pdf)
            with patch.object(pdf_converter, "convert_md_to_pdf", render):
                task = pdf_converter.start_pdf_generation(str(report), {})
                try:
                    # The queued job must block deletion even before it starts.
                    with self.assertRaises(server.HTTPException) as queued:
                        await server.delete_analysis_history("session1")
                    self.assertEqual(queued.exception.status_code, 409)
                    self.assertTrue(await asyncio.to_thread(entered.wait, 5))
                    with self.assertRaises(server.HTTPException) as caught:
                        await server.delete_analysis_history("session1")
                    self.assertEqual(caught.exception.status_code, 409)
                    self.assertTrue(report.exists())
                    self.assertIn("session1", server.analysis_sessions)
                finally:
                    release.set()
                    await task
                self.assertTrue(pdf.exists())
                response = await server.delete_analysis_history("session1")
                self.assertEqual(response["status"], "deleted")
                self.assertFalse(pdf.exists())
                self.assertFalse(report.exists())
        with tempfile.TemporaryDirectory() as directory:
            asyncio.run(scenario(directory))


if __name__ == "__main__":
    unittest.main(verbosity=2)
