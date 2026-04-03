import asyncio
from unittest.mock import AsyncMock

import app.routers.news_data as news_data_router


def test_query_stock_news_returns_sync_hint_without_runtime_fetch(monkeypatch):
    fake_service = AsyncMock()
    fake_service.query_news.return_value = []

    async def fake_get_news_data_service():
        return fake_service

    monkeypatch.setattr(news_data_router, "get_news_data_service", fake_get_news_data_service)

    result = asyncio.run(
        news_data_router.query_stock_news(
            symbol="600519",
            hours_back=24,
            limit=10,
            category=None,
            sentiment=None,
            current_user={"id": "test-user"},
        )
    )

    assert result["success"] is True
    assert result["data"]["symbol"] == "600519"
    assert result["data"]["total_count"] == 0
    assert result["data"]["data_source"] == "database"
    assert result["data"]["sync_required"] is True
    assert "先执行新闻同步" in result["data"]["sync_hint"]
