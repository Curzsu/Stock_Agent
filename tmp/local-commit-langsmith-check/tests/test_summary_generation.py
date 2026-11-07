import asyncio
import sys
import unittest
from pathlib import Path
from unittest.mock import AsyncMock, Mock, patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "agents"))
from langchain_core.messages import AIMessage

REPORT = (Path(__file__).parent / "fixtures/executive_summary.md").read_text(encoding="utf-8")


class TestExecutiveSummary(unittest.TestCase):
    def test_complete_summary_keeps_all_evidence_and_body(self):
        from src.utils.executive_summary import add_summary_identity, validate_executive_summary
        validate_executive_summary(REPORT)
        result = add_summary_identity(REPORT, "示例公司", "sh.600000", "2026-11-02")
        self.assertIn("**研究对象：** 示例公司（600000） · **分析日期：** 2026-11-02", result)
        self.assertLess(result.index("研究对象"), result.index("核心判断"))
        self.assertIn("新闻与历史估值缺失", result)
        self.assertIn("完整报告正文", result)
        self.assertEqual(result.count("经营现金流持续走弱"), 1)

    def test_rejects_missing_fake_duplicate_or_unfinished_summary(self):
        from src.utils.executive_summary import validate_executive_summary
        for source in (
            "# 报告\n\n## 执行摘要\n\n普通短段落。",
            "# 报告\n\n```\n## 摘要\n```\n\n## 正文\n只有代码中的假摘要。",
            REPORT + "\n\n## 摘要\n\n重复。",
            REPORT.split("## 公司概况")[0],
        ):
            with self.subTest(source=source[:45]), self.assertRaisesRegex(ValueError, "摘要"):
                validate_executive_summary(source)

    def test_rejects_overlong_or_overfragmented_summary_without_cutting_text(self):
        from src.utils.executive_summary import validate_executive_summary
        for replacement in ("原始证据不能截断" * 200, "\n\n".join(["一段解释。"] * 20)):
            report = REPORT.replace("现有材料支持经营改善", replacement)
            with self.subTest(replacement=replacement[:20]), self.assertRaisesRegex(ValueError, "摘要"):
                validate_executive_summary(report)

    def test_rejects_height_unbounded_markdown_in_new_summary(self):
        from src.utils.executive_summary import validate_executive_summary
        for extra in ("\n\n| 指标 | 数值 |\n| --- | --- |\n| PE | 20 |", "\n\n![图](test.png)", "\n\n### 嵌套标题", "\n\n    - 多级列表", "\n\n```\ncode\n```", "\n\n$$x=1$$"):
            with self.subTest(extra=extra), self.assertRaisesRegex(ValueError, "摘要"):
                validate_executive_summary(REPORT.replace("## 公司概况", extra + "\n\n## 公司概况"))

    def test_identity_escapes_markdown_and_does_not_invent_missing_identifiers(self):
        from src.utils.executive_summary import add_summary_identity
        result = add_summary_identity(REPORT, "A*[B]", "", "")
        self.assertIn(r"A\*\[B\]", result)
        self.assertIn("代码未提供", result)
        self.assertIn("日期未提供", result)

    def test_partial_research_carries_missing_dimensions_on_the_summary_page(self):
        from src.utils.executive_summary import add_summary_identity
        result = add_summary_identity(REPORT, "示例公司", "600000", "2026-11-02", ("技术面", "新闻面"))
        summary = result.split("## 公司概况")[0]
        self.assertIn("**资料缺口：** 技术面、新闻面未取得有效分析", summary)
        self.assertIn("相关判断待验证", summary)


class TestSummaryGeneration(unittest.TestCase):
    def test_overlong_summary_is_rewritten_once_with_original_evidence(self):
        from src.utils.summary_generation import generate_summary
        invalid = REPORT.replace("现有材料支持经营改善", "证据" * 600)
        calls = []

        async def invoke(messages):
            calls.append(messages)
            return AIMessage(content=invalid if len(calls) == 1 else REPORT)

        result = asyncio.run(generate_summary(Mock(ainvoke=invoke), [{"role": "user", "content": "ORIGINAL_EVIDENCE"}], Mock(), {}))
        self.assertEqual(result, REPORT.strip())
        self.assertEqual(len(calls), 2)
        self.assertEqual(calls[1][0]["content"], "ORIGINAL_EVIDENCE")
        self.assertIn("摘要", calls[1][-1]["content"])

    def test_two_invalid_summaries_fail_without_publishing_a_fragment(self):
        from src.utils.summary_generation import generate_summary
        llm = Mock(ainvoke=AsyncMock(return_value=AIMessage(content="# 报告\n\n没有摘要。")))
        log = Mock()
        with self.assertRaisesRegex(ValueError, "摘要"):
            asyncio.run(generate_summary(llm, [], log, {}))
        self.assertEqual(llm.ainvoke.await_count, 2)
        self.assertEqual(log.log_llm_interaction.call_count, 2)

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
