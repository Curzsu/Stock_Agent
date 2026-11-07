import sys
import unittest
from datetime import datetime
from pathlib import Path

import pandas as pd


WORKSPACE = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(WORKSPACE / "mcp-server"))

from src.baostock_data_source import DEFAULT_K_FIELDS, get_k_fields
from src.data_source_interface import NoDataFoundError
from src.tools.analysis import fetch_latest_financial_bundle, recent_quarters


class TestKLineFieldSelection(unittest.TestCase):
    def test_daily_defaults_keep_daily_metrics(self):
        fields = get_k_fields("d", None)

        self.assertEqual(fields, DEFAULT_K_FIELDS)
        self.assertIn("preclose", fields)
        self.assertIn("peTTM", fields)

    def test_weekly_and_monthly_defaults_use_period_safe_fields(self):
        expected = [
            "date",
            "code",
            "open",
            "high",
            "low",
            "close",
            "volume",
            "amount",
            "adjustflag",
        ]

        self.assertEqual(get_k_fields("w", None), expected)
        self.assertEqual(get_k_fields("m", None), expected)

    def test_explicit_fields_are_preserved(self):
        requested = ["date", "close"]

        self.assertEqual(get_k_fields("w", requested), requested)


class TestFinancialQuarterFallback(unittest.TestCase):
    def test_recent_quarters_crosses_year_boundary(self):
        candidates = recent_quarters(datetime(2026, 8, 10), limit=5)

        self.assertEqual(
            candidates,
            [
                ("2026", 3),
                ("2026", 2),
                ("2026", 1),
                ("2025", 4),
                ("2025", 3),
            ],
        )

    def test_financial_bundle_uses_latest_available_quarter(self):
        class FakeDataSource:
            def __init__(self):
                self.profit_calls = []
                self.detail_calls = []

            def get_profit_data(self, code, year, quarter):
                self.profit_calls.append((code, year, quarter))
                if (year, quarter) != ("2026", 1):
                    raise NoDataFoundError("not published")
                return pd.DataFrame([{"roeAvg": "12.3"}])

            def get_growth_data(self, code, year, quarter):
                self.detail_calls.append(("growth", code, year, quarter))
                return pd.DataFrame([{"YOYNI": "8.1"}])

            def get_balance_data(self, code, year, quarter):
                self.detail_calls.append(("balance", code, year, quarter))
                return pd.DataFrame([{"assetLiabRatio": "44.0"}])

            def get_dupont_data(self, code, year, quarter):
                self.detail_calls.append(("dupont", code, year, quarter))
                return pd.DataFrame([{"dupontROE": "12.3"}])

        data_source = FakeDataSource()
        year, quarter, bundle = fetch_latest_financial_bundle(
            data_source,
            "sh.600036",
            now=datetime(2026, 8, 10),
        )

        self.assertEqual((year, quarter), ("2026", 1))
        self.assertEqual(
            data_source.profit_calls,
            [
                ("sh.600036", "2026", 3),
                ("sh.600036", "2026", 2),
                ("sh.600036", "2026", 1),
            ],
        )
        self.assertEqual(
            data_source.detail_calls,
            [
                ("growth", "sh.600036", "2026", 1),
                ("balance", "sh.600036", "2026", 1),
                ("dupont", "sh.600036", "2026", 1),
            ],
        )
        self.assertEqual(
            set(bundle),
            {"profit", "growth", "balance", "dupont"},
        )


if __name__ == "__main__":
    unittest.main()
