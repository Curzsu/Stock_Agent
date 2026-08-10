import os
import sys
import unittest

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


if __name__ == "__main__":
    unittest.main(verbosity=2)
