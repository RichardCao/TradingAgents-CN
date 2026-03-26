import asyncio
import unittest
from datetime import datetime, timedelta
from unittest.mock import AsyncMock, patch

import pandas as pd

from app.services.favorites_service import (
    FavoritesService,
    _normalize_tags,
    build_historical_quote_fallback,
    infer_favorite_market_metadata,
)
from app.services.foreign_stock_service import ForeignStockService
from app.services.memory_state_manager import TaskState, TaskStatus
from app.services.stock_data_service import StockDataService
from app.services.tags_service import TagsService
from app.utils.report_language_utils import (
    get_report_section_title,
    normalize_report_markdown,
    normalize_reports_dict,
)


class TestRecentChanges(unittest.TestCase):
    def test_normalize_tags_removes_duplicates_and_blanks(self):
        tags = ["长期", " 短线 ", "", "长期", "短线", "  ", None, "港股"]

        normalized = _normalize_tags(tags)

        self.assertEqual(normalized, ["长期", "短线", "港股"])

    def test_report_language_utils_translate_english_headings_to_chinese(self):
        content = "## market_report\n\n### Neutral Analyst\n\n分析内容"

        normalized = normalize_report_markdown(content, "market_report", "zh-CN")

        self.assertIn("## 市场技术分析", normalized)
        self.assertIn("## 中性风险评估", normalized)
        self.assertNotIn("market_report", normalized)
        self.assertNotIn("Neutral Analyst", normalized)

    def test_normalize_reports_dict_applies_report_key_titles(self):
        reports = {
            "fundamentals_report": "fundamentals_report\n\n这是正文",
            "neutral_analyst": "1) neutral analyst",
        }

        normalized = normalize_reports_dict(reports, "zh-CN")

        self.assertEqual(
            get_report_section_title("fundamentals_report", "zh-CN"),
            "基本面分析",
        )
        self.assertTrue(normalized["fundamentals_report"].startswith("## 基本面分析"))
        self.assertIn("### 中性风险评估", normalized["neutral_analyst"])

    def test_favorites_service_format_favorite_normalizes_tags_and_currency(self):
        service = FavoritesService()
        favorite = {
            "stock_code": "09992",
            "stock_name": "泡泡玛特",
            "market": "港股",
            "added_at": datetime(2026, 3, 26, 12, 0, 0),
            "tags": ["潮玩", "港股", "潮玩", "  港股  ", ""],
            "notes": "测试"
        }

        formatted = service._format_favorite(favorite)

        self.assertEqual(formatted["currency"], "HKD")
        self.assertEqual(formatted["tags"], ["潮玩", "港股"])
        self.assertEqual(formatted["stock_code"], "09992")
        self.assertEqual(formatted["stock_name"], "泡泡玛特")

    def test_foreign_stock_service_format_hk_quote_preserves_change_percent(self):
        service = ForeignStockService.__new__(ForeignStockService)

        formatted = service._format_hk_quote(
            {
                "name": "泡泡玛特",
                "price": 188.6,
                "change_percent": "2.34%",
                "trade_date": "2026-03-26",
            },
            "09992",
            "akshare",
        )

        self.assertEqual(formatted["code"], "09992")
        self.assertEqual(formatted["name"], "泡泡玛特")
        self.assertEqual(formatted["change_percent"], 2.34)
        self.assertEqual(formatted["pct_chg"], 2.34)

    def test_infer_favorite_market_metadata_recognizes_exchange_and_board(self):
        self.assertEqual(
            infer_favorite_market_metadata("A股", "688001"),
            {"exchange": "上海证券交易所", "board": "科创板"},
        )
        self.assertEqual(
            infer_favorite_market_metadata("A股", "300750"),
            {"exchange": "深圳证券交易所", "board": "创业板"},
        )
        self.assertEqual(
            infer_favorite_market_metadata("港股", "09992"),
            {"exchange": "香港交易所", "board": None},
        )

    def test_build_historical_quote_fallback_uses_recent_close_and_prev_close(self):
        fallback = build_historical_quote_fallback(
            [
                {"trade_date": "2026-03-25", "close": 180.0},
                {"trade_date": "2026-03-26", "close": 189.0},
            ]
        )

        self.assertIsNotNone(fallback)
        self.assertEqual(fallback["current_price"], 189.0)
        self.assertEqual(fallback["trade_date"], "2026-03-26")
        self.assertEqual(fallback["change_percent"], 5.0)

    def test_stock_data_service_akshare_fallback_builds_basic_info(self):
        service = StockDataService()
        fake_df = pd.DataFrame(
            [
                {"symbol": "603083", "name": "剑桥科技", "market": "主板", "ts_code": "603083.SH"}
            ]
        )

        with patch("app.services.data_sources.akshare_adapter.AKShareAdapter") as mock_adapter_cls:
            mock_adapter = mock_adapter_cls.return_value
            mock_adapter.get_stock_list.return_value = fake_df

            result = asyncio.run(service._fetch_a_share_basic_info_from_akshare("603083"))

        self.assertIsNotNone(result)
        self.assertEqual(result["name"], "剑桥科技")
        self.assertEqual(result["source"], "akshare")
        self.assertEqual(result["sse"], "上海证券交易所")
        self.assertEqual(result["full_symbol"], "603083.SH")

    def test_stock_data_service_get_basic_info_uses_akshare_fallback_and_caches(self):
        service = StockDataService()

        class FakeCollection:
            async def find_one(self, *args, **kwargs):
                return None

        class FakeDB(dict):
            def __getitem__(self, key):
                return FakeCollection()

        fallback_doc = {
            "symbol": "603083",
            "code": "603083",
            "name": "剑桥科技",
            "market": "主板",
            "sse": "上海证券交易所",
            "full_symbol": "603083.SH",
            "source": "akshare",
        }

        with patch("app.services.stock_data_service.get_mongo_db", return_value=FakeDB()):
            with patch.object(service, "_fetch_a_share_basic_info_from_akshare", AsyncMock(return_value=fallback_doc)):
                with patch.object(service, "update_stock_basic_info", AsyncMock(return_value=True)) as mock_update:
                    result = asyncio.run(service.get_stock_basic_info("603083"))

        self.assertIsNotNone(result)
        self.assertEqual(result.name, "剑桥科技")
        self.assertEqual(result.symbol, "603083")
        mock_update.assert_awaited_once()

    def test_tags_service_replace_tag_name_deduplicates_per_stock(self):
        service = TagsService()

        updated, changed = service._replace_tag_name_in_favorites(
            [
                {"stock_code": "09992", "tags": ["成长", "长期", "成长"]},
                {"stock_code": "06166", "tags": ["成长", "核心"]},
            ],
            old_name="成长",
            new_name="核心",
        )

        self.assertTrue(changed)
        self.assertEqual(updated[0]["tags"], ["核心", "长期"])
        self.assertEqual(updated[1]["tags"], ["核心"])

    def test_task_state_to_dict_exposes_timing_fields(self):
        task = TaskState(
            task_id="task-1",
            user_id="user-1",
            stock_code="600519",
            status=TaskStatus.RUNNING,
            progress=45,
            start_time=datetime.now() - timedelta(seconds=12),
            estimated_duration=300,
        )

        data = task.to_dict()

        self.assertEqual(data["status"], "running")
        self.assertIn("elapsed_time", data)
        self.assertIn("remaining_time", data)
        self.assertIn("estimated_total_time", data)
        self.assertGreaterEqual(data["elapsed_time"], 11)
        self.assertLessEqual(data["estimated_total_time"], 300)
        self.assertGreaterEqual(data["remaining_time"], 0)


if __name__ == "__main__":
    unittest.main()
