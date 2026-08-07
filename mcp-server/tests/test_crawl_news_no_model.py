"""
D 项回归测试：crawl_news 不再依赖本地微调模型。

背景：
baostock_data_source.py 原本在 crawl_news 开头无条件调用
_load_risk_model() / _load_sentiment_model()，这两个函数依赖
/mnt/data/guyx/... 路径下的本地微调产物（risk/sentiment LoRA）。
该路径在当前部署环境不存在，模型加载失败返回 (None, None)，
随后 _analyze_risk / _analyze_sentiment 因 model 为 None 而跳过，
最终结果字段为 "未分析"。

用户已决定不再做微调相关任务，因此清理掉这批死代码：
- 删除 _load_risk_model / _load_sentiment_model / _analyze_risk / _analyze_sentiment
- crawl_news 不再调用模型加载，risk/sentiment 字段固定为 "未分析"

本测试固化清理后的行为契约：
1. crawl_news 不调用任何模型加载方法（这些方法已不存在）
2. 返回结果中风险/情感字段为 "未分析"
3. crawl_news 在无网络环境下不因模型加载而崩溃
"""
import os
import sys
import unittest
from unittest.mock import patch, MagicMock

import inspect

# 用 mcp-server 的 src 作为可导入包
MCP_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, MCP_ROOT)

from src.baostock_data_source import BaostockDataSource


# 一段最小化的"百度新闻搜索结果" HTML，含一条可被 h3>a 提取的条目
_FAKE_BAIDU_HTML = """
<html><head><title>百度新闻</title></head><body>
<div>
  <h3><a href="https://example.com/news/1">测试新闻标题</a></h3>
  <div class="c-abstract">这是一段测试摘要内容，用于验证爬取流程。</div>
</div>
</body></html>
"""


class TestCrawlNewsNoModelDependency(unittest.TestCase):
    """验证 crawl_news 清理本地微调模型依赖后的行为。"""

    def _make_source_with_no_model_methods(self):
        """构造一个 BaostockDataSource，并断言其不再有模型相关方法。"""
        source = BaostockDataSource.__new__(BaostockDataSource)
        return source

    def test_model_methods_removed(self):
        """_load_risk_model / _load_sentiment_model / _analyze_* 已删除。"""
        removed = [
            "_load_risk_model",
            "_load_sentiment_model",
            "_analyze_risk",
            "_analyze_sentiment",
        ]
        for name in removed:
            self.assertFalse(
                hasattr(BaostockDataSource, name),
                f"{name} 应已被删除，但仍存在于 BaostockDataSource",
            )

    def test_crawl_news_does_not_load_models(self):
        """crawl_news 源码不应再调用模型加载/分析方法。"""
        source = inspect.getsource(BaostockDataSource.crawl_news)
        for forbidden in ("_load_risk_model", "_load_sentiment_model",
                          "_analyze_risk", "_analyze_sentiment"):
            self.assertNotIn(
                forbidden, source,
                f"crawl_news 仍引用 {forbidden}，应已移除",
            )

        # mock requests.Session 避免真实网络，确认执行不报模型相关错误
        mock_session = MagicMock()
        mock_resp = MagicMock()
        mock_resp.status_code = 200
        mock_resp.text = _FAKE_BAIDU_HTML
        mock_resp.content = _FAKE_BAIDU_HTML.encode("utf-8")
        mock_resp.raise_for_status = MagicMock()
        mock_session.get.return_value = mock_resp

        source_obj = self._make_source_with_no_model_methods()
        with patch("src.baostock_data_source.requests.Session", return_value=mock_session):
            out = source_obj.crawl_news("测试查询", top_k=1)

        self.assertIsInstance(out, str)
        self.assertNotIn("模型", out)

    def test_crawl_news_marks_unanalyzed(self):
        """清理后风险/情感字段固定为 '未分析'。"""
        source = self._make_source_with_no_model_methods()

        mock_session = MagicMock()
        mock_resp = MagicMock()
        mock_resp.status_code = 200
        mock_resp.text = _FAKE_BAIDU_HTML
        mock_resp.content = _FAKE_BAIDU_HTML.encode("utf-8")
        mock_resp.raise_for_status = MagicMock()
        mock_session.get.return_value = mock_resp

        with patch("src.baostock_data_source.requests.Session", return_value=mock_session):
            result = source.crawl_news("测试查询", top_k=1)

        # 清理后每条新闻的风险/情感都应是 "未分析"
        self.assertIn("未分析", result)


if __name__ == "__main__":
    unittest.main()
