import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from unittest.mock import AsyncMock, patch

# Build a minimal app that mounts only the stocks router to avoid triggering app.main lifespan
from app.routers import stocks as stocks_router
from app.routers.auth import get_current_user


def create_test_app():
    app = FastAPI()
    app.include_router(stocks_router.router, prefix="/api")
    # Override auth dependency to bypass Bearer token in tests
    app.dependency_overrides[get_current_user] = lambda: {
        "id": "test",
        "username": "test",
        "is_admin": True,
        "roles": ["admin"],
    }
    return app


@pytest.fixture()
def client():
    app = create_test_app()
    with TestClient(app) as c:
        yield c


def test_kline_ok_source_and_adj(client):
    # Mock DataSourceManager fallback to return 2 bars
    items = [
        {"time": "2024-09-01", "open": 10.0, "high": 10.5, "low": 9.8, "close": 10.2, "volume": 100000.0, "amount": 2.3e6},
        {"time": "2024-09-02", "open": 10.2, "high": 10.8, "low": 10.0, "close": 10.6, "volume": 120000.0, "amount": 2.8e6},
    ]
    with patch("app.services.data_sources.manager.DataSourceManager.get_kline_with_fallback", return_value=(items, "tushare")):
        resp = client.get("/api/stocks/000001/kline", params={"period": "day", "limit": 2, "adj": "qfq"})
        assert resp.status_code == 200
        body = resp.json()
        assert body.get("success") is True
        data = body.get("data")
        assert data["code"] == "000001"
        assert data["period"] == "day"
        assert data["limit"] == 2
        assert data["adj"] == "qfq"
        assert data["source"] == "tushare"
        assert isinstance(data["items"], list) and len(data["items"]) == 2


def test_kline_invalid_period_returns_400(client):
    resp = client.get("/api/stocks/000001/kline", params={"period": "2m", "limit": 10})
    assert resp.status_code == 400
    j = resp.json()
    # FastAPI default error format
    assert j["detail"].startswith("不支持的period")


def test_news_ok_with_announcements_and_source(client):
    db_items = [
        {
            "title": "公告样例",
            "source": "tushare",
            "publish_time": "2024-09-02",
            "url": "http://x",
            "content": "",
            "summary": "",
        },
        {
            "title": "新闻样例",
            "source": "tushare",
            "publish_time": "2024-09-02 10:00:00",
            "url": "http://y",
            "content": "",
            "summary": "",
        },
    ]
    fake_news_service = AsyncMock()
    fake_news_service.query_news.return_value = db_items
    fake_sync_service = AsyncMock()

    with patch("app.services.news_data_service.get_news_data_service", AsyncMock(return_value=fake_news_service)), \
         patch("app.worker.akshare_sync_service.get_akshare_sync_service", AsyncMock(return_value=fake_sync_service)):
        resp = client.get("/api/stocks/000001/news", params={"days": 2, "limit": 2, "include_announcements": True})
        assert resp.status_code == 200
        body = resp.json()
        assert body.get("success") is True
        data = body.get("data")
        assert data["code"] == "000001"
        assert data["days"] == 2
        assert data["limit"] == 2
        assert data["include_announcements"] is True
        assert data["source"] == "database"
        assert isinstance(data["items"], list) and len(data["items"]) == 2
        assert data["items"][0]["source"] == "tushare"


def test_hk_news_uses_foreign_stock_service(client):
    fake_result = {
        "code": "09992",
        "days": 3,
        "limit": 2,
        "source": "akshare",
        "items": [
            {
                "title": "泡泡玛特港股新闻样例",
                "publish_time": "2026-03-28 10:00:00",
                "url": "https://example.com/hk-news",
                "summary": "新闻摘要",
                "source": "AKShare-东方财富",
            }
        ],
    }

    mock_service = AsyncMock()
    mock_service.get_hk_news.return_value = fake_result

    with patch("app.services.foreign_stock_service.ForeignStockService", return_value=mock_service):
        resp = client.get("/api/stocks/09992/news", params={"days": 3, "limit": 2})

    assert resp.status_code == 200
    body = resp.json()
    assert body.get("success") is True
    data = body.get("data")
    assert data["code"] == "09992"
    assert data["days"] == 3
    assert data["limit"] == 2
    assert data["source"] == "akshare"
    assert len(data["items"]) == 1
    assert data["items"][0]["title"] == "泡泡玛特港股新闻样例"


def test_a_share_news_cache_miss_returns_sync_hint_without_runtime_sync(client):
    fake_news_service = AsyncMock()
    fake_news_service.query_news.return_value = []

    with patch("app.services.news_data_service.get_news_data_service", AsyncMock(return_value=fake_news_service)):
        resp = client.get("/api/stocks/000001/news", params={"days": 2, "limit": 2})

    assert resp.status_code == 200
    body = resp.json()
    assert body.get("success") is True
    data = body.get("data")
    assert data["code"] == "000001"
    assert data["source"] == "database"
    assert data["items"] == []
    assert data["sync_required"] is True
    assert "先执行新闻同步" in data["sync_hint"]
