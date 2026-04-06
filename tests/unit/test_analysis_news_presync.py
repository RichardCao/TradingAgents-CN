import asyncio

from app.models.analysis import AnalysisParameters, SingleAnalysisRequest
import app.services.analysis_presync_service as analysis_presync_service
from app.services.analysis_presync_service import run_analysis_pre_sync
from tradingagents.agents.analysts.news_analyst import (
    _has_usable_news_content,
    _is_presync_required_news_message,
)
from tradingagents.tools.unified_news_tool import UnifiedNewsAnalyzer


def test_run_analysis_pre_sync_marks_news_sync_failure(monkeypatch):
    async def fake_sync_single_stock(request, background_tasks, current_user):
        return {
            "success": True,
            "message": "市场数据同步成功",
            "data": {"overall_success": True},
        }

    async def fake_sync_single_stock_news(
        symbol,
        data_sources,
        hours_back,
        max_news_per_source,
        current_user,
    ):
        return {
            "success": True,
            "message": "新闻同步未写入任何数据",
            "data": {"sync_stats": {"successful_saves": 0}},
        }

    monkeypatch.setattr(analysis_presync_service, "sync_single_stock", fake_sync_single_stock)
    monkeypatch.setattr(
        analysis_presync_service,
        "sync_single_stock_news",
        fake_sync_single_stock_news,
    )

    request = SingleAnalysisRequest(
        symbol="600519",
        parameters=AnalysisParameters(
            market_type="A股",
            selected_analysts=["market", "news"],
        ),
    )

    summary = asyncio.run(
        run_analysis_pre_sync(
            current_user={"id": "test-user"},
            request=request,
        )
    )

    news_step = next(step for step in summary["steps"] if step["type"] == "news")

    assert news_step["success"] is False
    assert summary["overall_success"] is False


def test_a_share_news_analysis_reads_database_only(monkeypatch):
    analyzer = UnifiedNewsAnalyzer(toolkit=object())

    monkeypatch.setattr(analyzer, "_get_news_from_database", lambda stock_code, max_news: "")

    result = analyzer._get_a_share_news("600519", 10)

    assert "已预同步新闻数据" in result
    assert "分析阶段只读" in result


def test_presync_required_news_message_is_not_treated_as_usable_content():
    message = (
        "❌ 未找到 A股 600519 的已预同步新闻数据。\n\n"
        "当前分析链路已切换为“分析前预同步，分析阶段只读”。\n"
        "请先完成新闻预同步后再重新发起分析。"
    )

    assert _is_presync_required_news_message(message) is True
    assert _has_usable_news_content(message) is False


def test_run_analysis_pre_sync_marks_social_media_missing(monkeypatch):
    async def fake_sync_single_stock(request, background_tasks, current_user):
        return {
            "success": True,
            "message": "市场数据同步成功",
            "data": {"overall_success": True},
        }

    async def fake_check_existing_social_media_data(symbol, analysis_date, require_native=False):
        return {
            "success": False,
            "message": "未找到已同步社媒数据，请先导入或保存社媒消息后再分析",
            "data": {"recent_count": 0},
        }

    monkeypatch.setattr(analysis_presync_service, "sync_single_stock", fake_sync_single_stock)
    monkeypatch.setattr(
        analysis_presync_service,
        "_check_existing_social_media_data",
        fake_check_existing_social_media_data,
    )
    class _FakeSocialSyncResult:
        saved_messages = 0
        generated_messages = 0
        used_existing_social_data = False
        latest_publish_time = None

    async def fake_sync_a_share_native_social_media(**kwargs):
        return _FakeSocialSyncResult()

    monkeypatch.setattr(
        analysis_presync_service,
        "sync_a_share_native_social_media",
        fake_sync_a_share_native_social_media,
    )

    request = SingleAnalysisRequest(
        symbol="600519",
        parameters=AnalysisParameters(
            market_type="A股",
            selected_analysts=["market", "social"],
        ),
    )

    summary = asyncio.run(
        run_analysis_pre_sync(
            current_user={"id": "test-user"},
            request=request,
        )
    )

    social_step = next(step for step in summary["steps"] if step["type"] == "social_media")

    assert social_step["success"] is False
    assert summary["overall_success"] is False


def test_check_existing_social_media_data_requires_native_for_a_share(monkeypatch):
    class _FakeCollection:
        async def count_documents(self, query):
            if query.get("data_source", {}).get("$in"):
                return 0
            return 2

        async def find_one(self, query, sort=None):
            if query.get("data_source", {}).get("$in"):
                return None
            return {
                "symbol": "600519",
                "platform": "news_proxy",
                "data_source": "stock_news_proxy",
                "publish_time": "2026-04-03T09:00:00",
            }

    class _FakeDB:
        social_media_messages = _FakeCollection()

    monkeypatch.setattr(analysis_presync_service, "get_mongo_db", lambda: _FakeDB())

    result = asyncio.run(
        analysis_presync_service._check_existing_social_media_data(
            symbol="600519",
            analysis_date="2026-04-03",
            require_native=True,
        )
    )

    assert result["success"] is False
    assert "原生社媒" in result["message"]
    assert result["data"]["recent_count"] == 0
    assert result["data"]["native_recent_count"] == 0


def test_run_analysis_pre_sync_uses_a_share_native_social_sync(monkeypatch):
    async def fake_sync_single_stock(request, background_tasks, current_user):
        return {
            "success": True,
            "message": "市场数据同步成功",
            "data": {"overall_success": True},
        }

    async def fake_check_existing_social_media_data(symbol, analysis_date, require_native=False):
        return {
            "success": False,
            "message": "未找到已同步社媒数据",
            "data": {"recent_count": 0},
        }

    class _FakeSocialSyncResult:
        source = "stock_irm_cninfo"
        source_details = ["stock_irm_cninfo"]
        saved_messages = 3
        generated_messages = 3
        used_existing_social_data = False
        fallback_used = False
        fallback_source = None
        latest_publish_time = None

    async def fake_sync_a_share_native_social_media(**kwargs):
        return _FakeSocialSyncResult()

    monkeypatch.setattr(analysis_presync_service, "sync_single_stock", fake_sync_single_stock)
    monkeypatch.setattr(
        analysis_presync_service,
        "_check_existing_social_media_data",
        fake_check_existing_social_media_data,
    )
    monkeypatch.setattr(
        analysis_presync_service,
        "sync_a_share_native_social_media",
        fake_sync_a_share_native_social_media,
    )

    request = SingleAnalysisRequest(
        symbol="600519",
        parameters=AnalysisParameters(
            market_type="A股",
            selected_analysts=["market", "social"],
        ),
    )

    summary = asyncio.run(
        run_analysis_pre_sync(
            current_user={"id": "test-user"},
            request=request,
        )
    )

    social_step = next(step for step in summary["steps"] if step["type"] == "social_media")

    assert social_step["success"] is True
    assert social_step["data"]["source"] == "stock_irm_cninfo"
    assert social_step["data"]["saved_messages"] == 3
    assert summary["overall_success"] is True


def test_run_analysis_pre_sync_uses_native_social_without_news_fallback(monkeypatch):
    async def fake_sync_single_stock(request, background_tasks, current_user):
        return {
            "success": True,
            "message": "市场数据同步成功",
            "data": {"overall_success": True},
        }

    async def fake_check_existing_social_media_data(symbol, analysis_date, require_native=False):
        return {
            "success": False,
            "message": "未找到已同步社媒数据",
            "data": {"recent_count": 0},
        }

    captured_kwargs = {}

    class _FakeSocialSyncResult:
        source = "stock_irm_cninfo"
        source_details = ["stock_irm_cninfo"]
        saved_messages = 2
        generated_messages = 2
        used_existing_social_data = False
        fallback_used = False
        fallback_source = None
        latest_publish_time = None

    async def fake_sync_a_share_native_social_media(**kwargs):
        captured_kwargs.update(kwargs)
        return _FakeSocialSyncResult()

    monkeypatch.setattr(analysis_presync_service, "sync_single_stock", fake_sync_single_stock)
    monkeypatch.setattr(
        analysis_presync_service,
        "_check_existing_social_media_data",
        fake_check_existing_social_media_data,
    )
    monkeypatch.setattr(
        analysis_presync_service,
        "sync_a_share_native_social_media",
        fake_sync_a_share_native_social_media,
    )

    request = SingleAnalysisRequest(
        symbol="600519",
        parameters=AnalysisParameters(
            market_type="A股",
            selected_analysts=["social"],
        ),
    )

    summary = asyncio.run(
        run_analysis_pre_sync(
            current_user={"id": "test-user"},
            request=request,
        )
    )

    social_step = next(step for step in summary["steps"] if step["type"] == "social_media")

    assert captured_kwargs["allow_news_fallback"] is False
    assert social_step["success"] is True
    assert social_step["data"]["fallback_used"] is False
