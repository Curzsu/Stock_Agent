import sys
import unittest
from pathlib import Path


WORKSPACE = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(WORKSPACE / "mcp-server"))

from src.baostock_data_source import DEFAULT_K_FIELDS, get_k_fields


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


if __name__ == "__main__":
    unittest.main()
