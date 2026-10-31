"""Offline contracts for the Eisvogel report preparation and renderer."""

import os
import json
import asyncio
import subprocess
import sys
import tempfile
import threading
import time
import unittest
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "agents"))


class ReportPreparationTests(unittest.TestCase):
    def test_keeps_intro_tables_math_and_code_when_removing_cover_title(self):
        from src.utils.pdf_styles import prepare_report

        source = """# 长江电力(sh.600900) 综合分析报告

[TOC]

这是章节前的摘要，不能丢失。

## 基本面分析

| 指标 | 数值 |
| --- | --- |
| ROE | 12.5% |

公式：$P = EPS \\times PE$。

```markdown
# 代码中的标题
[TOC]
```

## 风险因素

来水变化。
"""
        report = prepare_report(source, analysis_date="2026-10-31")
        self.assertEqual(report.metadata["title"], "长江电力")
        self.assertIn("600900", report.metadata["subtitle"])
        self.assertEqual(report.metadata["date"], "2026-10-31")
        self.assertIn("这是章节前的摘要，不能丢失。", report.markdown)
        self.assertIn("| ROE | 12.5% |", report.markdown)
        self.assertIn(r"$P = EPS \times PE$", report.markdown)
        self.assertIn("```markdown\n# 代码中的标题\n[TOC]\n```", report.markdown)
        self.assertNotIn("# 长江电力", report.markdown)
        self.assertNotIn("[TOC]\n\n这是", report.markdown)
        self.assertIn("# 基本面分析", report.markdown)

    def test_explicit_cover_fields_override_title_and_preserve_leading_zero(self):
        from src.utils.pdf_styles import prepare_report

        report = prepare_report(
            "# 原公司(sz.002594) 综合分析报告\n\n正文。",
            company_name="平安银行 & 研究",
            stock_code="000001",
            analysis_date="2026-10-30",
        )
        self.assertEqual(report.metadata["title"], "平安银行 & 研究")
        self.assertIn("000001", report.metadata["subtitle"])
        self.assertEqual(report.metadata["date"], "2026-10-30")
        self.assertIn("正文。", report.markdown)

    def test_report_without_h1_or_sections_still_keeps_all_content(self):
        from src.utils.pdf_styles import prepare_report

        report = prepare_report("只有正文。\n\n## 原二级标题\n\n结论。")
        self.assertIn("只有正文。", report.markdown)
        self.assertIn("## 原二级标题", report.markdown)
        self.assertIn("结论。", report.markdown)
        self.assertEqual(report.metadata["title"], "金融分析报告")

    def test_chinese_font_can_be_configured_without_changing_template(self):
        from src.utils.pdf_styles import prepare_report

        with patch.dict(os.environ, {"PDF_CJK_FONT": "Noto Sans CJK SC"}):
            report = prepare_report("# 测试报告\n\n正文")
        self.assertEqual(report.metadata["CJKmainfont"], "Noto Sans CJK SC")

    def test_first_indented_code_block_keeps_its_markdown_indentation(self):
        from src.utils.pdf_styles import prepare_report

        report = prepare_report("# Cover\n\n    # literal code heading\n    original second line\n")
        self.assertTrue(report.markdown.startswith("    # literal code heading\n"))
        self.assertIn("    original second line", report.markdown)


class PdfConversionTests(unittest.TestCase):
    def setUp(self):
        from src.utils import pdf_converter

        self.converter = pdf_converter
        self.directory = tempfile.TemporaryDirectory()
        self.addCleanup(self.directory.cleanup)
        self.root = Path(self.directory.name)
        self.source = self.root / "md" / "中文 report.md"
        self.source.parent.mkdir()
        self.source.write_text("# 平安银行(000001) 综合分析报告\n\n## 摘要\n\n正文。", encoding="utf-8")
        self.output = Path(pdf_converter.derive_pdf_path(str(self.source)))
        toolchain = patch.object(pdf_converter, "_resolve_toolchain", return_value=("pandoc", "tectonic"))
        toolchain.start()
        self.addCleanup(toolchain.stop)

    def test_only_publishes_complete_pdf_and_passes_utf8_metadata(self):
        def render(command, *, cwd, timeout):
            self.assertFalse(self.output.exists())
            metadata = json.loads(Path(command[command.index("--metadata-file") + 1]).read_text(encoding="utf-8"))
            self.assertEqual(metadata["title"], "平安银行")
            self.assertIn("000001", metadata["subtitle"])
            self.assertEqual(metadata["date"], "2026-10-31")
            self.assertIn("--template", command)
            template = Path(command[command.index("--template") + 1])
            self.assertTrue(template.is_file())
            self.assertEqual(template.name, "eisvogel.latex")
            self.assertIn("--lua-filter", command)
            self.assertTrue(Path(command[command.index("--lua-filter") + 1]).is_file())
            cover_options = [arg for arg in command if arg.startswith("titlepage-background=")]
            self.assertTrue(cover_options, "The cover illustration must be passed independently of the report directory")
            cover = Path(cover_options[0].split("=", 1)[1])
            self.assertTrue(cover.is_absolute())
            self.assertTrue(cover.is_file())
            self.assertIn("--pdf-engine=tectonic", command)
            self.assertGreater(timeout, 0)
            Path(command[command.index("--output") + 1]).write_bytes(b"%PDF-1.7\ncomplete report\n%%EOF\n")

        with patch.object(self.converter, "_run_pandoc", side_effect=render):
            result = self.converter.convert_md_to_pdf(str(self.source), analysis_date="2026-10-31")
        self.assertEqual(result, str(self.output))
        self.assertTrue(self.output.read_bytes().startswith(b"%PDF-"))
        self.assertEqual(self.converter.get_pdf_status(str(self.source))["status"], "ready")
        self.assertEqual(list(self.output.parent.glob("finex-pdf-*")), [])

    def test_timeout_records_terminal_failure_without_partial_pdf(self):
        def render(command, **kwargs):
            Path(command[command.index("--output") + 1]).write_bytes(b"%PDF-incomplete")
            raise subprocess.TimeoutExpired(command, 2)

        with patch.object(self.converter, "_run_pandoc", side_effect=render):
            self.assertIsNone(self.converter.convert_md_to_pdf(str(self.source)))
        self.assertFalse(self.output.exists())
        status = self.converter.get_pdf_status(str(self.source))
        self.assertEqual(status["status"], "failed")
        self.assertIn("超时", status["message"])
        self.assertEqual(list(self.output.parent.glob("finex-pdf-*")), [])

    def test_failed_regeneration_does_not_damage_existing_pdf(self):
        self.output.parent.mkdir()
        previous = b"%PDF-1.7\nprevious report\n%%EOF\n"
        self.output.write_bytes(previous)
        failure = subprocess.CalledProcessError(1, ["pandoc"], stderr="missing font")
        with patch.object(self.converter, "_run_pandoc", side_effect=failure):
            self.assertIsNone(self.converter.convert_md_to_pdf(str(self.source)))
        self.assertEqual(self.output.read_bytes(), previous)

    def test_success_exit_without_valid_pdf_is_failure(self):
        def render(command, **kwargs):
            Path(command[command.index("--output") + 1]).write_text("not a PDF", encoding="utf-8")

        with patch.object(self.converter, "_run_pandoc", side_effect=render):
            self.assertIsNone(self.converter.convert_md_to_pdf(str(self.source)))
        self.assertFalse(self.output.exists())
        self.assertEqual(self.converter.get_pdf_status(str(self.source))["status"], "failed")

    def test_missing_toolchain_reports_actionable_failure(self):
        with patch.object(self.converter, "_resolve_toolchain", side_effect=RuntimeError("请运行 scripts/setup_pdf.ps1 安装 Pandoc 和 Tectonic")):
            self.assertIsNone(self.converter.convert_md_to_pdf(str(self.source)))
        self.assertIn("setup_pdf.ps1", self.converter.get_pdf_status(str(self.source))["message"])

    def test_missing_cover_asset_is_reported_without_publishing_pdf(self):
        templates = self.root / "incomplete-templates"
        templates.mkdir()
        for name in ("eisvogel.latex", "finex-warm.tex"):
            (templates / name).write_text("test template", encoding="utf-8")

        def render(command, **kwargs):
            Path(command[command.index("--output") + 1]).write_bytes(b"%PDF-1.7\nreport\n%%EOF\n")

        with patch.object(self.converter, "TEMPLATE_DIR", templates), patch.object(self.converter, "_run_pandoc", side_effect=render):
            self.assertIsNone(self.converter.convert_md_to_pdf(str(self.source)))
        self.assertFalse(self.output.exists())
        self.assertIn("封面插画", self.converter.get_pdf_status(str(self.source))["message"])

    def test_diagnostics_keep_latex_error_in_stdout_when_stderr_has_download_notes(self):
        failure = subprocess.CalledProcessError(
            1, ["pandoc"], output="Error producing PDF.\n! font missing: example-font",
            stderr="note: downloading a-package.sty\n" * 150,
        )
        with patch.object(self.converter, "_run_pandoc", side_effect=failure):
            self.assertIsNone(self.converter.convert_md_to_pdf(str(self.source)))
        self.assertIn("font missing", self.converter.get_pdf_status(str(self.source))["message"])
        self.assertIn("a-package.sty", self.output.with_suffix(".pdf.log").read_text(encoding="utf-8"))

    def test_incomplete_pdf_with_valid_header_is_not_published(self):
        def render(command, **kwargs):
            Path(command[command.index("--output") + 1]).write_bytes(b"%PDF-1.7\ntruncated stream")

        with patch.object(self.converter, "_run_pandoc", side_effect=render):
            self.assertIsNone(self.converter.convert_md_to_pdf(str(self.source)))
        self.assertFalse(self.output.exists())

    def test_abandoned_pending_build_becomes_terminal(self):
        self.output.parent.mkdir()
        self.output.with_suffix(".pdf.status.json").write_text(json.dumps({
            "status": "pending", "updated_at": time.time() - 1000, "timeout": 300,
        }), encoding="utf-8")
        self.assertEqual(self.converter.get_pdf_status(str(self.source))["status"], "failed")

    def test_parallel_builds_keep_separate_content_and_workspaces(self):
        barrier = threading.Barrier(2)
        workspaces = []

        def render(command, *, cwd, timeout):
            workspaces.append(cwd)
            source = Path(command[-1]).read_text(encoding="utf-8")
            barrier.wait(timeout=5)
            Path(command[command.index("--output") + 1]).write_bytes(b"%PDF-1.7\n" + source.encode("utf-8") + b"\n%%EOF\n")

        sources = []
        for name in ("first", "second"):
            source = self.source.parent / f"{name}.md"
            source.write_text(f"# {name}\n\n独立正文 {name}", encoding="utf-8")
            sources.append(str(source))
        with patch.object(self.converter, "_run_pandoc", side_effect=render), ThreadPoolExecutor(max_workers=2) as pool:
            results = list(pool.map(self.converter.convert_md_to_pdf, sources))
        self.assertEqual(len(set(workspaces)), 2)
        for name, result in zip(("first", "second"), results):
            self.assertIsNotNone(result)
            self.assertIn(f"独立正文 {name}", Path(result).read_bytes().decode("utf-8"))


class BackgroundPdfTests(unittest.IsolatedAsyncioTestCase):
    async def test_background_build_updates_state_without_blocking_event_loop(self):
        from src.utils import pdf_converter

        started = threading.Event()
        release = threading.Event()

        def convert(*args):
            started.set()
            release.wait(timeout=5)
            return "report.pdf"

        state = {}
        with patch.object(pdf_converter, "convert_md_to_pdf", side_effect=convert):
            task = asyncio.create_task(pdf_converter.generate_pdf_background("report.md", state))
            try:
                for _ in range(100):
                    if started.is_set():
                        break
                    await asyncio.sleep(0.01)
                self.assertTrue(started.is_set())
                self.assertFalse(task.done())
            finally:
                release.set()
            await task
        self.assertEqual(state["pdf_path"], "report.pdf")

    async def test_background_failure_clears_previous_state(self):
        from src.utils import pdf_converter

        state = {"pdf_path": "old.pdf"}
        with patch.object(pdf_converter, "convert_md_to_pdf", return_value=None):
            await pdf_converter.generate_pdf_background("report.md", state)
        self.assertIsNone(state["pdf_path"])


class PandocProcessTests(unittest.TestCase):
    def test_process_timeout_is_enforced(self):
        from src.utils.pdf_converter import _run_pandoc

        with tempfile.TemporaryDirectory() as directory:
            started = time.monotonic()
            with self.assertRaises(subprocess.TimeoutExpired):
                _run_pandoc([sys.executable, "-c", "import time; time.sleep(30)"], cwd=directory, timeout=0.2)
            self.assertLess(time.monotonic() - started, 10)

    def test_process_failure_keeps_stderr_for_diagnostics(self):
        from src.utils.pdf_converter import _run_pandoc

        with tempfile.TemporaryDirectory() as directory:
            with self.assertRaises(subprocess.CalledProcessError) as error:
                _run_pandoc([sys.executable, "-c", "import sys; sys.stderr.write('font unavailable'); sys.exit(7)"], cwd=directory, timeout=10)
        self.assertEqual(error.exception.returncode, 7)
        self.assertIn("font unavailable", error.exception.stderr)


if __name__ == "__main__":
    unittest.main()
