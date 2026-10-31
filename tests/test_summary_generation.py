import asyncio
import sys
import unittest
from pathlib import Path
from unittest.mock import AsyncMock, Mock, patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "agents"))
from langchain_core.messages import AIMessage


class TestSummaryGeneration(unittest.TestCase):
    def test_summary_output_limit_is_independently_configurable(self):
        from src.utils.summary_generation import summary_max_tokens
        with patch.dict("os.environ", {"SUMMARY_MAX_TOKENS": "16000", "LLM_MAX_TOKENS": "6000"}):
            self.assertEqual(summary_max_tokens(), 16000)
        with patch.dict("os.environ", {"SUMMARY_MAX_TOKENS": "0"}):
            with self.assertRaises(ValueError):
                summary_max_tokens()

    def test_length_retry_is_bounded_and_diagnostics_survive_failure(self):
        from src.utils.summary_generation import generate_summary
        llm = Mock(ainvoke=AsyncMock(return_value=AIMessage(
            content="unfinished", response_metadata={"finish_reason": "length"},
            usage_metadata={"input_tokens": 10, "output_tokens": 20, "total_tokens": 30},
        )))
        log = Mock()
        with self.assertRaisesRegex(ValueError, "length"):
            asyncio.run(generate_summary(llm, [], log, {"max_tokens": 12000}))
        self.assertEqual(llm.ainvoke.await_count, 2)
        self.assertEqual(log.log_llm_interaction.call_count, 2)
        attempt = log.log_llm_interaction.call_args.kwargs
        self.assertEqual(attempt["token_usage"]["output_tokens"], 20)
        self.assertEqual(attempt["model_config"]["finish_reason"], "length")

    def test_other_invalid_output_is_not_retried(self):
        from src.utils.summary_generation import generate_summary
        for message in (AIMessage(content=""), AIMessage(content="filtered", response_metadata={"finish_reason": "content_filter"})):
            llm = Mock(ainvoke=AsyncMock(return_value=message))
            with self.assertRaises(ValueError):
                asyncio.run(generate_summary(llm, [], Mock(), {}))
            self.assertEqual(llm.ainvoke.await_count, 1)

    def test_total_timeout_covers_both_attempts(self):
        from src.utils.summary_generation import generate_summary
        async def invoke(messages):
            await asyncio.sleep(0.03)
            return AIMessage(content="partial", response_metadata={"finish_reason": "length"})
        with self.assertRaises(asyncio.TimeoutError):
            asyncio.run(asyncio.wait_for(generate_summary(Mock(ainvoke=invoke), [], Mock(), {}), timeout=0.045))


if __name__ == "__main__":
    unittest.main()
