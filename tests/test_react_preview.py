import tempfile
import unittest
from contextlib import ExitStack
from pathlib import Path
from unittest.mock import patch

from fastapi.testclient import TestClient

from backend import server


class ReactPreviewTest(unittest.TestCase):
    def setUp(self):
        contexts = ExitStack()
        self.addCleanup(contexts.close)
        self.build_dir = Path(contexts.enter_context(tempfile.TemporaryDirectory()))
        contexts.enter_context(patch.object(server, "react_dist_dir", self.build_dir, create=True))
        self.client = contexts.enter_context(
            TestClient(server.app, base_url="http://localhost", client=("127.0.0.1", 50000))
        )

    def build_preview(self):
        html = '<script type="module" src="/react-preview/assets/index-Ab12Cd34.js"></script>'
        (self.build_dir / "index.html").write_text(html, encoding="utf-8")
        assets = self.build_dir / "assets"
        assets.mkdir()
        (assets / "index-Ab12Cd34.js").write_text("export {};", encoding="utf-8")
        return html

    def test_preview_home_and_direct_workbench_share_revalidated_entry(self):
        html = self.build_preview()
        for path in (
            "/react-preview/",
            "/react-preview/app/history",
            "/react-preview/app/analysis/abc123",
            "/react-preview/app/analysis/abc123/report",
        ):
            with self.subTest(path=path):
                response = self.client.get(path)
                self.assertEqual(response.status_code, 200)
                self.assertEqual(response.text, html)
                self.assertEqual(response.headers["cache-control"], "no-cache")

    def test_hashed_asset_is_cached_and_unknown_urls_keep_404(self):
        self.build_preview()
        response = self.client.get("/react-preview/assets/index-Ab12Cd34.js")
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.text, "export {};")
        self.assertEqual(response.headers["cache-control"], "public, max-age=31536000, immutable")
        for path in ("/react-preview/assets/missing.js", "/react-preview/unknown", "/api/unknown"):
            with self.subTest(path=path):
                self.assertEqual(self.client.get(path).status_code, 404)

    def test_preview_without_build_does_not_affect_legacy_home(self):
        self.assertEqual(self.client.get("/react-preview/").status_code, 404)
        self.assertEqual(self.client.get("/react-preview/assets/absent.js").status_code, 404)
        self.assertEqual(self.client.get("/").status_code, 200)
        self.assertEqual(self.client.get("/api/health").json()["status"], "healthy")

    def test_legacy_static_urls_work_and_source_files_are_private(self):
        for path in ("/static/workbench.js", "/static/workbench.css", "/static/assets/fonts/FINEXRound-Regular.woff"):
            with self.subTest(path=path):
                self.assertEqual(self.client.get(path).status_code, 200)
        self.assertEqual(self.client.get("/static/src/index.html").status_code, 404)
        self.assertEqual(self.client.get("/static/package.json").status_code, 404)

    def test_preview_is_restricted_to_local_requests(self):
        self.build_preview()
        with TestClient(server.app, base_url="http://localhost", client=("203.0.113.4", 50000)) as remote:
            for path in (
                "/react-preview/",
                "/react-preview/app/history",
                "/react-preview/app/analysis/abc123/report",
                "/react-preview/assets/index-Ab12Cd34.js",
            ):
                with self.subTest(path=path):
                    self.assertEqual(remote.get(path).status_code, 403)


if __name__ == "__main__":
    unittest.main()
