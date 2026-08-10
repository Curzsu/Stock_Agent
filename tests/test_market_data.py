import os
import sys
import unittest


PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, PROJECT_ROOT)

from backend.market_data import build_market_payload, normalize_stock_code


class TestMarketData(unittest.TestCase):
    def test_normalize_stock_code(self):
        self.assertEqual(normalize_stock_code("600519"), "sh.600519")
        self.assertEqual(normalize_stock_code("000001"), "sz.000001")
        self.assertEqual(normalize_stock_code("sh.600519"), "sh.600519")
        with self.assertRaises(ValueError):
            normalize_stock_code("123")

    def test_payload_calculates_moving_averages(self):
        rows = [
            {
                "date": f"2026-08-{day:02d}",
                "open": str(day),
                "high": str(day + 1),
                "low": str(day - 1),
                "close": str(day),
                "volume": "1000",
                "turn": "0.2",
                "pctChg": "1.0",
                "peTTM": "24.6",
                "pbMRQ": "8.1",
            }
            for day in range(1, 22)
        ]
        payload = build_market_payload("sh.600519", rows)
        self.assertTrue(payload["ok"])
        self.assertEqual(payload["latest_trade_date"], "2026-08-21")
        self.assertEqual(payload["candles"][4]["ma5"], 3.0)
        self.assertEqual(payload["candles"][20]["ma20"], 11.5)
        self.assertEqual(payload["quote"]["pe_ttm"], 24.6)

    def test_empty_rows_return_explicit_unavailable_payload(self):
        payload = build_market_payload("sh.600519", [])
        self.assertFalse(payload["ok"])
        self.assertEqual(payload["error"], "未获取到个股行情数据")


if __name__ == "__main__":
    unittest.main(verbosity=2)
