"""P2-3 简化版测试：extract_stock_info 共享模块。

背景：
backend/server.py 和 agents/src/main.py 各自有一套 extract_stock_info，
逻辑重复且会漂移。P2-3 把 server 版抽成共享模块 src.utils.stock_extractor，
两入口都改调它。本测试对共享模块的 extract_stock_info(query) 做特征化测试，
锁住 server 版的原有行为。
"""
import unittest
import os, sys
PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, PROJECT_ROOT)
sys.path.insert(0, os.path.join(PROJECT_ROOT, "agents"))


class TestExtractStockInfo(unittest.TestCase):
    def test_company_with_code_in_parens(self):
        """分析嘉友国际(603871) -> company=嘉友国际, code=603871"""
        from src.utils.stock_extractor import extract_stock_info
        name, code = extract_stock_info("分析嘉友国际(603871)")
        self.assertEqual(name, "嘉友国际")
        self.assertEqual(code, "603871")

    def test_bare_stock_code(self):
        """603871 -> code=603871, name=None"""
        from src.utils.stock_extractor import extract_stock_info
        name, code = extract_stock_info("603871")
        self.assertEqual(code, "603871")

    def test_company_name_only(self):
        """比亚迪 -> name=比亚迪, code=002594 (from COMPANY_CODE_MAP)"""
        from src.utils.stock_extractor import extract_stock_info
        name, code = extract_stock_info("比亚迪")
        self.assertEqual(name, "比亚迪")
        self.assertEqual(code, "002594")

    def test_company_name_with_stock_keyword(self):
        """比亚迪这只股票 -> name=比亚迪"""
        from src.utils.stock_extractor import extract_stock_info
        name, code = extract_stock_info("比亚迪这只股票")
        self.assertEqual(name, "比亚迪")

    def test_analyze_company(self):
        """分析茅台 -> name=茅台"""
        from src.utils.stock_extractor import extract_stock_info
        name, code = extract_stock_info("分析茅台")
        self.assertEqual(name, "茅台")

    def test_empty_query(self):
        """空查询 -> name=None, code=None"""
        from src.utils.stock_extractor import extract_stock_info
        name, code = extract_stock_info("")
        self.assertIsNone(name)
        self.assertIsNone(code)


if __name__ == "__main__":
    unittest.main()
