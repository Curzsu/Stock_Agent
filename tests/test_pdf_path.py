"""P2-6 测试：derive_pdf_path 共享路径推断函数。

背景：
server.py 有两处、pdf_converter.py 有一处，重复了同一个路径推断逻辑：
reports/md/xxx.md -> reports/pdf/xxx.pdf，否则与 MD 同目录同名换 .pdf。
目录约定一变三处都得改。抽取 derive_pdf_path(md_path) -> str 消除重复。
"""
import unittest
import os
import sys

PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, PROJECT_ROOT)
sys.path.insert(0, os.path.join(PROJECT_ROOT, "agents"))


class TestDerivePdfPath(unittest.TestCase):
    def test_md_in_reports_md_dir(self):
        """reports/md/xxx.md -> reports/pdf/xxx.pdf"""
        from src.utils.pdf_converter import derive_pdf_path
        result = derive_pdf_path("/app/reports/md/report_2026.md")
        # os.path.normpath 归一化路径分隔符，保证 Windows/Linux 都能比较
        self.assertEqual(os.path.normpath(result),
                         os.path.normpath(os.path.join("/app", "reports", "pdf", "report_2026.pdf")))

    def test_md_in_arbitrary_dir(self):
        """不在 md 目录下时，PDF 与 MD 同目录同名"""
        from src.utils.pdf_converter import derive_pdf_path
        result = derive_pdf_path("/app/output/report.md")
        self.assertEqual(os.path.normpath(result), os.path.normpath("/app/output/report.pdf"))

    def test_windows_path(self):
        """Windows 路径也能处理"""
        from src.utils.pdf_converter import derive_pdf_path
        result = derive_pdf_path(r"E:\proj\reports\md\report.md")
        # 用 os.path.normpath 归一化后比较
        self.assertTrue(result.endswith(os.path.join("pdf", "report.pdf")))


if __name__ == "__main__":
    unittest.main()
