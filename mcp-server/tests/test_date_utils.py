"""Calendar boundaries and failures must not invent a latest trading date."""

import sys
import unittest
from datetime import datetime
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock, patch

import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from src.tools import date_utils


class TestLatestTradingDate(unittest.TestCase):
    def latest(self, today, trading_dates=None, error=None):
        tools = {}
        app = SimpleNamespace(tool=lambda: lambda fn: tools.setdefault(fn.__name__, fn))

        def calendar(start_date, end_date):
            return pd.DataFrame([
                {"calendar_date": day, "is_trading_day": "1"}
                for day in (trading_dates or []) if start_date <= day <= end_date
            ], columns=["calendar_date", "is_trading_day"])

        source = SimpleNamespace(get_trade_dates=Mock(side_effect=error or calendar))
        date_utils.register_date_utils_tools(app, source)
        with patch.object(date_utils, "datetime", wraps=datetime) as clock:
            clock.now.return_value = today
            return tools["get_latest_trading_date"]()

    def test_month_end_includes_the_last_three_days(self):
        self.assertEqual(self.latest(datetime(2026, 8, 31), ["2026-08-28", "2026-08-31", "2026-09-01"]), "2026-08-31")

    def test_month_start_holiday_uses_previous_month(self):
        self.assertEqual(self.latest(datetime(2026, 10, 1), ["2026-09-30", "2026-10-09"]), "2026-09-30")

    def test_new_year_uses_previous_year(self):
        self.assertEqual(self.latest(datetime(2027, 1, 1), ["2026-12-31"]), "2026-12-31")

    def test_missing_calendar_returns_an_explicit_error(self):
        self.assertTrue(self.latest(datetime(2026, 10, 1), []).startswith("Error:"))

    def test_unavailable_calendar_returns_an_explicit_error(self):
        self.assertTrue(self.latest(datetime(2026, 10, 1), error=RuntimeError("calendar unavailable")).startswith("Error:"))


if __name__ == "__main__":
    unittest.main()
