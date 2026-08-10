import os
import sys
import unittest
from unittest.mock import AsyncMock, patch

from fastapi.testclient import TestClient


PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, PROJECT_ROOT)
sys.path.insert(0, os.path.join(PROJECT_ROOT, "agents"))

from backend import server


class TestAnalysisSessionApi(unittest.TestCase):
    def setUp(self):
        server.analysis_sessions.clear()
        self.client = TestClient(server.app)
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
        self.session.status = "degraded"
        self.session.agent_details["news"]["status"] = "failed"
        with patch.object(server, "retry_agent_and_summary", new=AsyncMock()):
            response = self.client.post("/api/analysis/session1/retry/news")
        self.assertEqual(response.status_code, 202)
        self.assertEqual(response.json()["status"], "retrying")

        response = self.client.post("/api/analysis/session1/retry/fundamental")
        self.assertEqual(response.status_code, 409)

        response = self.client.post("/api/analysis/session1/retry/summary")
        self.assertEqual(response.status_code, 422)

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


if __name__ == "__main__":
    unittest.main(verbosity=2)
