"""P2-6 测试：derive_pdf_path 共享路径推断函数。

背景：
server.py 有两处、pdf_converter.py 有一处，重复了同一个路径推断逻辑：
reports/md/xxx.md -> reports/pdf/xxx.pdf，否则与 MD 同目录同名换 .pdf。
目录约定一变三处都得改。抽取 derive_pdf_path(md_path) -> str 消除重复。
"""
import unittest
import os
import sys
import tempfile
import threading
import ntpath
import posixpath
from pathlib import Path
from types import SimpleNamespace
from concurrent.futures import ThreadPoolExecutor
from unittest.mock import patch

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
        """在任何 CI 主机上验证 Windows 的原生路径语义。"""
        from src.utils import pdf_converter
        with patch.object(pdf_converter, "os", SimpleNamespace(path=ntpath)):
            result = pdf_converter.derive_pdf_path(r"E:\proj\reports\md\report.md")
        self.assertEqual(result, r"E:\proj\reports\pdf\report.pdf")

    def test_posix_path(self):
        from src.utils import pdf_converter
        with patch.object(pdf_converter, "os", SimpleNamespace(path=posixpath)):
            result = pdf_converter.derive_pdf_path("/app/reports/md/report.md")
        self.assertEqual(result, "/app/reports/pdf/report.pdf")

    def test_parallel_pdf_rendering_keeps_each_reports_content(self):
        from src.utils import pdf_converter

        barrier = threading.Barrier(2)

        class FakeHTML:
            def __init__(self, filename=None, string=None, base_url=None):
                barrier.wait(timeout=5)
                self.content = string if string is not None else Path(filename).read_text(encoding="utf-8")

            def write_pdf(self, pdf_path):
                barrier.wait(timeout=5)
                Path(pdf_path).write_text(self.content, encoding="utf-8")

        with tempfile.TemporaryDirectory(dir=PROJECT_ROOT) as directory:
            def render(name):
                output = Path(directory) / f"{name}.pdf"
                try:
                    pdf_converter._render_with_weasyprint(f"<p>{name}</p>", str(output), directory)
                    return output.read_text(encoding="utf-8")
                except Exception as exc:
                    return f"render failed: {exc}"

            with patch.object(pdf_converter, "WeasyHTML", FakeHTML, create=True), ThreadPoolExecutor(max_workers=2) as pool:
                results = list(pool.map(render, ["first", "second"]))
            self.assertEqual(results, ["<p>first</p>", "<p>second</p>"])
            self.assertEqual(list(Path(directory).glob("*.html")), [])


if __name__ == "__main__":
    unittest.main()
