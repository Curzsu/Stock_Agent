"""Run the actual Pandoc AST formatter without LaTeX or network calls."""
import json
import shutil
import subprocess
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
FILTER = ROOT / "agents/src/utils/pdf_templates/report-layout.lua"
PORTABLE = ROOT / ".tools/pdf/pandoc/pandoc.exe"
PANDOC = str(PORTABLE) if PORTABLE.is_file() else shutil.which("pandoc")


def nodes(value, kind):
    result = []
    if isinstance(value, dict):
        if value.get("t") == kind:
            result.append(value)
        for child in value.values():
            result.extend(nodes(child, kind))
    elif isinstance(value, list):
        for child in value:
            result.extend(nodes(child, kind))
    return result


@unittest.skipUnless(PANDOC, "Pandoc is an optional PDF dependency")
class ReportLayoutTests(unittest.TestCase):
    def render(self, source, output="json", filtered=True):
        command = [PANDOC, "--from=markdown+lists_without_preceding_blankline", "--to=" + output]
        if filtered:
            command += ["--lua-filter", str(FILTER)]
        result = subprocess.run(command, input=source, capture_output=True, text=True, encoding="utf-8", timeout=20, check=True)
        return json.loads(result.stdout) if output == "json" else result.stdout

    def test_emphasis_preserves_existing_bold_code_math_and_link_targets(self):
        doc = self.render('ROE为6.75%，毛利率57.89%，市盈率（PE）21.09倍。\n\n**MACD**，SOME_PEOPLE，`ROE=1`，$PE=2$，[来源](https://example.com/ROE?PE=1)。\n\n```text\nROE 3%\n```')
        strong = nodes(doc, "Strong")
        text = ["".join(n["c"] for n in nodes(item, "Str")) for item in strong]
        for term in ("ROE", "6.75%", "毛利率", "57.89%", "市盈率", "PE", "21.09倍", "MACD"):
            self.assertIn(term, text)
        self.assertTrue(all(not nodes(item["c"], "Strong") for item in strong))
        self.assertEqual(nodes(doc, "Code")[0]["c"][1], "ROE=1")
        self.assertEqual(nodes(doc, "CodeBlock")[0]["c"][1], "ROE 3%")
        self.assertEqual(nodes(doc, "Math")[0]["c"][1], "PE=2")
        self.assertEqual(nodes(doc, "Link")[0]["c"][2][0], "https://example.com/ROE?PE=1")
        self.assertNotIn("PEOPLE", text)

    def test_labeled_lists_become_tables_without_changing_values_or_links(self):
        source = '# 基本面分析\n\n- **盈利能力：** ROE 6.75%。\n- **现金流：** 经营现金流与净利润比值160%，[来源](https://example.com/report)。\n\n# 技术分析\n\n- **趋势：** MA20附近。\n'
        doc = self.render(source)
        self.assertEqual(len(nodes(doc, "Table")), 1)
        self.assertEqual(len(nodes(doc, "BulletList")), 1)
        self.assertEqual(nodes(doc, "Link")[0]["c"][2][0], "https://example.com/report")
        self.assertIn("160%", self.render(source, "plain"))

    def test_both_ends_of_value_ranges_are_emphasized_and_dates_stay_plain(self):
        doc = self.render('参考价格27.80-29.40元；股息3.17%至3.5%。\n\n区间为27.80 - 29.40元，日期2026-10-31。')
        strong = nodes(doc, "Strong")
        text = ["".join(n["c"] for n in nodes(item, "Str")) for item in strong]
        self.assertIn("27.80-29.40元", text)
        self.assertEqual(text.count("27.80-29.40元"), 2)
        self.assertTrue(all("2026" not in item for item in text))
        self.assertTrue(all(not nodes(item["c"], "Strong") for item in strong))

    def test_unstructured_lists_are_not_forced_into_tables(self):
        doc = self.render('# 估值分析\n\n- PE 21倍。\n- 无固定标签的解释。\n')
        self.assertFalse(nodes(doc, "Table"))
        self.assertEqual(len(nodes(doc, "BulletList")), 1)

    def test_table_labels_retain_links_math_code_and_notes(self):
        source = '# 基本面分析\n\n- **[ROE](https://example.com/metric)：** 6.75%。\n- **$P/E$：** 21倍。\n- **`EPS`：** 数据缺失。\n- **来源[^1]：** 公开财报。\n\n[^1]: 财务说明。\n'
        doc = self.render(source)
        self.assertEqual(len(nodes(doc, "Table")), 1)
        self.assertEqual(nodes(doc, "Link")[0]["c"][2][0], "https://example.com/metric")
        self.assertEqual(nodes(doc, "Math")[0]["c"][1], "P/E")
        self.assertEqual(nodes(doc, "Code")[0]["c"][1], "EPS")
        self.assertEqual(len(nodes(doc, "Note")), 1)

    def test_summary_and_risk_panels_do_not_wrap_tables_or_change_facts(self):
        source = '# 执行摘要\n\n价格29.74元，保持谨慎。\n\n| 指标 | 值 |\n| --- | --- |\n| ROE | 6.75% |\n\n# 风险因素\n\n1. 来水变化。\n2. 利率波动。\n'
        latex = self.render(source, "latex")
        self.assertIn(r"\begin{FinexSummary}", latex)
        self.assertIn(r"\begin{FinexRisk}", latex)
        self.assertIn(r"\Needspace{10\baselineskip}", latex)
        self.assertLess(latex.index(r"\end{FinexSummary}"), latex.index(r"\begin{longtable}"))
        self.assertIn("29.74", latex)
        self.assertIn("来水变化", latex)


if __name__ == "__main__":
    unittest.main()
