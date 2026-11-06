"""Exercise real LangSmith/LangChain contexts without uploading any data."""
import asyncio
import importlib.util
import os
import sys
import unittest
from pathlib import Path
from unittest.mock import Mock, patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "agents"))
# The offline fake model needs no optional local inference frameworks.
os.environ["USE_TORCH"] = "0"
os.environ["USE_TF"] = "0"
os.environ["USE_FLAX"] = "0"

from langchain_core.language_models.fake_chat_models import FakeListChatModel
from langchain_core.messages import AIMessage
from langchain_core.outputs import ChatGeneration, ChatResult
from langsmith import Client, tracing_context
from langsmith.run_helpers import get_current_run_tree


class RecordingClient(Client):
    """Retain SDK runs at the upload boundary; never start a network client."""
    def __init__(self):
        super().__init__(api_key="test-only", auto_batch_tracing=False)
        self.created = []
        self.updated = []

    def create_run(self, name, inputs, run_type, **kwargs):
        self.created.append(dict(name=name, inputs=inputs, run_type=run_type, **kwargs))

    def update_run(self, run_id, **kwargs):
        self.updated.append(dict(id=run_id, **kwargs))


class UsageModel(FakeListChatModel):
    def _generate(self, messages, stop=None, run_manager=None, **kwargs):
        return ChatResult(generations=[ChatGeneration(message=AIMessage(
            content="unfinished",
            response_metadata={"finish_reason": "length"},
            usage_metadata={"input_tokens": 11, "output_tokens": 23, "total_tokens": 34},
        ))])


def state(analysis_id):
    return {"data": {"query": "分析茅台", "stock_code": "sh.600519"},
            "metadata": {"analysis_id": analysis_id}, "messages": []}


class TestObservability(unittest.TestCase):
    def setUp(self):
        if importlib.util.find_spec("src.utils.observability") is None:
            self.fail("FINEX observability integration has not been implemented")
        from src.utils import observability
        self.obs = observability
        self.env = patch.dict(os.environ, {
            "LANGSMITH_TRACING": "true", "LANGSMITH_API_KEY": "test-only",
            "LANGSMITH_PROJECT": "finex-test", "LANGSMITH_TRACING_SAMPLING_RATE": "1",
            "LANGSMITH_AGENT_ID": "", "LANGSMITH_AGENT_ENVIRONMENT": "",
        })
        self.env.start()
        self.addCleanup(self.env.stop)
        from langsmith import utils
        utils.get_env_var.cache_clear()
        self.addCleanup(utils.get_env_var.cache_clear)
        self.client = RecordingClient()
        self.client_patch = patch.object(observability, "get_client", return_value=self.client)
        self.client_patch.start()
        self.addCleanup(self.client_patch.stop)

    def test_disabled_or_missing_key_creates_no_client_or_runs(self):
        async def check():
            for setting in ({"LANGSMITH_TRACING": "false"}, {"LANGSMITH_API_KEY": ""}):
                with patch.dict(os.environ, setting), self.obs.analysis_trace(state("off")) as run:
                    self.assertIsNone(run)
                    await FakeListChatModel(responses=["ok"]).ainvoke("ping")
            self.obs.get_client.assert_not_called()
        asyncio.run(check())
        self.assertEqual(self.client.created, [])

    def test_parallel_analyses_keep_model_usage_and_validation_errors_isolated(self):
        from src.utils.agent_output import extract_analysis_text

        async def analyst(s):
            await asyncio.sleep(0)
            response = await UsageModel(responses=["unused"]).ainvoke("ping")
            try:
                extract_analysis_text({"messages": [response]})
            except ValueError as error:
                return {"data": {"technical_analysis_error": str(error)}}

        async def run(analysis_id):
            s = state(analysis_id)
            with self.obs.analysis_trace(s) as root:
                result = await self.obs.invoke_agent(analyst, s, "technical")
                self.obs.finish_trace(root, result)

        async def both():
            await asyncio.gather(run("one"), run("two"))
        asyncio.run(both())
        roots = [r for r in self.client.created if r["name"] == "finex.analysis"]
        self.assertEqual(len(roots), 2)
        llms = [r for r in self.client.created if r["run_type"] == "llm"]
        self.assertEqual(len(llms), 2)
        self.assertEqual({r["extra"]["metadata"]["analysis_id"] for r in llms}, {"one", "two"})
        self.assertEqual({r["trace_id"] for r in llms}, {r["id"] for r in roots})
        for model in llms:
            update = next(r for r in self.client.updated if str(r["id"]) == str(model["id"]))
            message = update["outputs"]["generations"][0][0]["message"]["kwargs"]
            self.assertEqual(message["usage_metadata"]["total_tokens"], 34)
            self.assertEqual(message["response_metadata"]["finish_reason"], "length")
        failures = [r for r in self.client.updated if r.get("error")]
        self.assertEqual(len(failures), 4)  # Two agent spans and two root spans.

    def test_cancellation_marks_span_and_restores_context(self):
        async def hang(s):
            await asyncio.sleep(10)

        async def run():
            with self.assertRaises(asyncio.TimeoutError):
                with self.obs.analysis_trace(state("timeout")):
                    await asyncio.wait_for(self.obs.invoke_agent(hang, state("timeout"), "news"), 0.02)
            self.assertIsNone(get_current_run_tree())
        asyncio.run(run())
        self.assertEqual(len([r for r in self.client.updated if r.get("error")]), 2)

    def test_retry_has_new_root_and_same_analysis_id(self):
        s = state("same")
        s["metadata"]["retry"] = "technical"
        for operation in ("analysis", "retry"):
            with self.obs.analysis_trace(s, operation=operation) as root:
                self.obs.finish_trace(root, {"data": {"technical_analysis": "ok"}})
        roots = self.client.created
        self.assertEqual([r["name"] for r in roots], ["finex.analysis", "finex.retry"])
        self.assertNotEqual(roots[0]["id"], roots[1]["id"])
        self.assertEqual({r["extra"]["metadata"]["analysis_id"] for r in roots}, {"same"})
        self.assertEqual(roots[1]["extra"]["metadata"]["retry"], "technical")

    def test_client_initialization_failure_does_not_stop_analysis(self):
        self.obs.get_client.side_effect = RuntimeError("unavailable")
        with self.obs.analysis_trace(state("fallback")) as run:
            self.assertIsNone(run)
        self.assertIsNone(get_current_run_tree())

    def test_mcp_queue_and_execution_are_separate_child_spans(self):
        from langchain_core.tools import StructuredTool
        from src.tools.mcp_client import serialize_mcp_tools

        async def probe():
            await asyncio.sleep(0.01)
            return "ok"

        tool = serialize_mcp_tools([StructuredTool.from_function(
            coroutine=probe, name="probe", description="Offline data probe.",
        )])[0]

        async def run():
            with self.obs.analysis_trace(state("queue")):
                self.assertEqual(await asyncio.gather(tool.ainvoke({}), tool.ainvoke({})), ["ok", "ok"])
        asyncio.run(run())
        phases = [r for r in self.client.created if r["name"].startswith("mcp.")]
        self.assertEqual(sorted(r["name"] for r in phases), ["mcp.execute", "mcp.execute", "mcp.queue", "mcp.queue"])
        for phase in phases:
            self.assertEqual(phase["extra"]["metadata"]["analysis_id"], "queue")
            self.assertEqual(phase["extra"]["metadata"]["tool"], "probe")

    def test_workflow_scopes_all_five_roles(self):
        from src.utils.workflow_builder import build_workflow

        def agent(key):
            async def run(s):
                await FakeListChatModel(responses=["ok"]).ainvoke("ping")
                return {"data": {key: "ok"}}
            return run

        graph = build_workflow(**{f"{k}_agent": agent(v) for k, v in self.obs.RESULT_KEYS.items()})
        result = asyncio.run(self.obs.invoke_workflow(graph, state("graph")))
        self.assertEqual(result["data"]["final_report"], "ok")
        self.assertEqual({r["name"] for r in self.client.created if r["name"].startswith("finex.agent.")},
                         {f"finex.agent.{key}" for key in self.obs.RESULT_KEYS})
        self.assertEqual(len([r for r in self.client.created if r["run_type"] == "llm"]), 5)

    def test_backend_retry_groups_agent_and_summary_under_retry_root(self):
        sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
        from backend import server
        session = server.AnalysisStatus(
            analysis_id="retry-test", status="running", agent_details=server.new_agent_details(),
            progress={},
            initial_data=state("retry-test")["data"],
        )

        async def technical(s):
            return {"data": {"technical_analysis": "技术分析有效。"}}

        async def summary(s):
            return {"data": {"summary_error": "汇总被截断"}}

        with patch.dict(server.analysis_sessions, {"retry-test": session}, clear=True):
            asyncio.run(server.retry_agent_and_summary("retry-test", "technical", technical, summary))
        root = next(r for r in self.client.created if r["name"] == "finex.retry")
        roles = [r for r in self.client.created if r["name"].startswith("finex.agent.")]
        self.assertEqual({r["parent_run_id"] for r in roles}, {root["id"]})
        self.assertTrue(next(r for r in self.client.updated if r["id"] == root["id"])["error"])

    def test_agent_based_workspace_routes_without_project_override(self):
        from langsmith import utils
        utils.get_env_var.cache_clear()
        self.addCleanup(utils.get_env_var.cache_clear)
        with patch.dict(os.environ, {"LANGSMITH_AGENT_ID": "finex", "LANGSMITH_AGENT_ENVIRONMENT": "development"}):
            os.environ.pop("LANGSMITH_PROJECT", None)
            os.environ.pop("LANGCHAIN_PROJECT", None)
            async def probe():
                with self.obs.analysis_trace(state("agent-address")) as run:
                    self.assertEqual(run.address["id"], "finex")
                    self.assertEqual(run.address["environment"], "DEVELOPMENT")
                    await FakeListChatModel(responses=["ok"]).ainvoke("ping")
            asyncio.run(probe())
        root, model = self.client.created
        self.assertEqual(model["address"], root["address"])
        self.assertEqual(model["parent_run_id"], root["id"])
        self.assertIsNone(model.get("session_name"))

    def test_shutdown_closes_client_with_deadline_and_allows_reinitialization(self):
        client = Mock()
        with patch.object(self.obs, "_client", client):
            asyncio.run(self.obs.flush_traces())
            client.close.assert_called_once_with(timeout=5)
            self.obs.get_client.cache_clear.assert_called_once()
            self.assertIsNone(self.obs._client)

    def test_sender_errors_do_not_fail_or_repeat_business_operation(self):
        for boundary in ("create_run", "update_run"):
            operation = Mock(return_value="research result")
            with patch.object(self.client, boundary, side_effect=OSError("sender unavailable")):
                with self.obs.analysis_trace(state("sender-failure")):
                    result = operation()
            self.assertEqual(result, "research result")
            operation.assert_called_once()
            self.assertIsNone(get_current_run_tree())

    def test_sender_failure_does_not_hide_business_exception(self):
        with patch.object(self.client, "update_run", side_effect=OSError("sender unavailable")):
            with self.assertRaisesRegex(ValueError, "business failure"):
                with self.obs.analysis_trace(state("business-failure")):
                    raise ValueError("business failure")
        self.assertIsNone(get_current_run_tree())

    def test_failed_retry_is_recorded_even_when_previous_summary_is_completed(self):
        sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
        from backend import server
        session = server.AnalysisStatus(
            analysis_id="degraded-retry", status="running", progress={},
            agent_details=server.new_agent_details(), initial_data=state("degraded-retry")["data"],
        )
        for detail in session.agent_details.values():
            detail["status"] = "completed"

        async def failed(s):
            return {"data": {"technical_analysis_error": "模型超时"}}

        with patch.dict(server.analysis_sessions, {session.analysis_id: session}, clear=True):
            asyncio.run(server.retry_agent_and_summary(session.analysis_id, "technical", failed))
        self.assertEqual(session.status, "degraded")
        root = next(r for r in self.client.created if r["name"] == "finex.retry")
        update = next(r for r in self.client.updated if r["id"] == root["id"])
        self.assertIn("模型超时", update["error"] or "")


if __name__ == "__main__":
    unittest.main()
