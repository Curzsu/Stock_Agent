"""Reader-facing cleanup must preserve evidence and technical literals."""

import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "agents"))


class ReportPresentationTests(unittest.TestCase):
    def clean(self, text):
        from src.utils.report_presentation import polish_report_markdown
        return polish_report_markdown(text)

    def test_internal_field_names_become_readable_without_duplicate_metric_names(self):
        source = ('加权平均净资产收益率 **roeAvg** 为 **15.99%**；动态市盈率 **peTTM** 约 **20.10倍**。\n'
                  '| **毛利率 (gpMargin)** | **61.67%** |\n'
                  '| **经营现金流占比 (CFOToOR)** | **0.70** |\n'
                  '应收账款周转率 **NRTurnRatio** 为 **10.40次**。')
        result = self.clean(source)
        self.assertIn('加权平均净资产收益率 为 **15.99%**', result)
        self.assertIn('市盈率（TTM） 约 **20.10倍**', result)
        self.assertIn('| **毛利率** | **61.67%** |', result)
        self.assertIn('| **经营现金流/营业收入** | **0.70** |', result)
        self.assertNotIn('roeAvg', result)
        self.assertNotIn('NRTurnRatio', result)
        self.assertIn('**10.40次**', result)

    def test_ratio_periods_and_useful_financial_acronyms_remain_explicit(self):
        result = self.clean('peTTM 20倍；pbMRQ 3倍；epsTTM 1.41元。ROE、MACD、RSI和PB-MRQ仍可使用。')
        self.assertEqual(result, '市盈率（TTM） 20倍；市净率（最近季末） 3倍；每股收益（TTM） 1.41元。ROE、MACD、RSI和PB-MRQ仍可使用。')

    def test_observation_wrappers_and_repeated_advice_label_do_not_hide_information(self):
        source = ('## 基本面分析\n\n- **观察项：核心财务指标**：收入10亿元。\n'
                  '- **观察项：** **数据缺失**，未取得财报。\n\n'
                  '## 投资建议\n\n- **投资建议**：等待业绩验证。\n- **适合投资者类型：** 长期投资者。\n'
                  '## 附录\n\n- **投资建议：** 引述原文。')
        result = self.clean(source)
        self.assertIn('- **核心财务指标**：收入10亿元。', result)
        self.assertIn('- **数据缺失**，未取得财报。', result)
        self.assertIn('- **配置思路**：等待业绩验证。', result)
        self.assertIn('- **投资建议：** 引述原文。', result)
        self.assertNotIn('观察项', result)

    def test_code_math_links_urls_and_unknown_fields_are_untouched(self):
        source = ('`roeAvg`；$roeAvg=1$；\\(peTTM=2\\)；[源](https://example.com/?roeAvg=1)；https://example.com/CFOToOR。\n'
                  '[源](https://example.com/a(stats)/roeAvg)；[来源][roeAvg]；[^CFOToOR]。\n'
                  '[roeAvg]: https://example.com/source\n'
                  '\n```text\n- **观察项：** roeAvg\n```\n'
                  '\n    roeAvg = 1\n'
                  '\n$$\nroeAvg = 2\n$$\n'
                  '\nunknownField 3倍。')
        self.assertEqual(self.clean(source), source)

    def test_cleanup_is_idempotent(self):
        source = '## 投资建议\n\n- **观察项：投资建议：** 以peTTM 20倍作为观察数据。'
        result = self.clean(source)
        self.assertEqual(self.clean(result), result)

    def test_pdf_preparation_applies_the_same_cleanup_to_existing_reports(self):
        from src.utils.pdf_styles import prepare_report
        prepared = prepare_report('# 公司(600000) 综合分析报告\n\n## 估值分析\n\n- **观察项：估值指标：** peTTM为20.10倍。')
        self.assertNotIn('观察项', prepared.markdown)
        self.assertNotIn('peTTM', prepared.markdown)
        self.assertIn('20.10倍', prepared.markdown)


if __name__ == '__main__':
    unittest.main()
