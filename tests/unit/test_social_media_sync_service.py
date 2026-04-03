from datetime import datetime

import app.services.social_media_sync_service as social_sync_service


class _FakeSocialService:
    def __init__(self):
        self.saved_payload = None

    async def save_social_media_messages(self, messages):
        self.saved_payload = messages
        return {
            "saved": len(messages),
            "failed": 0,
        }


def test_sync_social_media_from_news_proxy_generates_messages(monkeypatch):
    fake_service = _FakeSocialService()

    async def fake_load_recent_news_docs(symbol, hours_back, max_items):
        return [
            {
                "title": "贵州茅台获机构上调评级",
                "summary": "机构认为公司盈利能力仍具韧性。",
                "source": "财联社",
                "publish_time": datetime(2026, 4, 3, 9, 30),
                "sentiment": "positive",
                "sentiment_score": 0.8,
                "keywords": ["茅台", "评级"],
                "category": "news",
                "language": "zh-CN",
            }
        ]

    async def fake_has_existing_social_media_data(symbol, hours_back):
        return {"recent_count": 0, "latest_publish_time": None}

    async def fake_get_social_media_service():
        return fake_service

    async def fake_save_sync_history_record(**kwargs):
        return None

    monkeypatch.setattr(social_sync_service, "_load_recent_news_docs", fake_load_recent_news_docs)
    monkeypatch.setattr(social_sync_service, "_has_existing_social_media_data", fake_has_existing_social_media_data)
    monkeypatch.setattr(social_sync_service, "get_social_media_service", fake_get_social_media_service)
    monkeypatch.setattr(social_sync_service, "save_sync_history_record", fake_save_sync_history_record)

    result = social_sync_service.sync_social_media_from_news_proxy(
        symbol="600519",
        current_user={"id": "test-user"},
        hours_back=72,
        max_items=20,
        save_history=True,
        skip_if_existing=True,
    )

    import asyncio
    resolved = asyncio.run(result)

    assert resolved.saved_messages == 1
    assert resolved.generated_messages == 1
    assert fake_service.saved_payload is not None
    assert fake_service.saved_payload[0]["platform"] == "news_proxy"
    assert fake_service.saved_payload[0]["data_source"] == "stock_news_proxy"


def test_sync_social_media_from_news_proxy_skips_when_existing(monkeypatch):
    async def fake_has_existing_social_media_data(symbol, hours_back):
        return {
            "recent_count": 3,
            "latest_publish_time": datetime(2026, 4, 3, 10, 0),
        }

    async def fake_save_sync_history_record(**kwargs):
        return None

    monkeypatch.setattr(social_sync_service, "_has_existing_social_media_data", fake_has_existing_social_media_data)
    monkeypatch.setattr(social_sync_service, "save_sync_history_record", fake_save_sync_history_record)

    import asyncio

    resolved = asyncio.run(
        social_sync_service.sync_social_media_from_news_proxy(
            symbol="600519",
            current_user={"id": "test-user"},
            save_history=True,
            skip_if_existing=True,
        )
    )

    assert resolved.skipped_existing is True
    assert resolved.used_existing_social_data is True


def test_sync_a_share_native_social_media_generates_native_messages(monkeypatch):
    fake_service = _FakeSocialService()

    async def fake_has_existing_social_media_data(symbol, hours_back):
        return {"recent_count": 0, "latest_publish_time": None}

    async def fake_load_a_share_native_social_rows(symbol, max_items):
        return {
            "source": "stock_irm_cninfo",
            "rows": [
                {
                    "公司简称": "贵州茅台",
                    "问题": "请问公司今年分红规划如何？",
                    "提问者": "价值投资者",
                    "提问时间": "2026-04-01 10:00:00",
                    "问题编号": "q-001",
                    "回答ID": "a-001",
                    "回答内容": "公司将综合经营情况审慎制定分红方案。",
                    "回答者": "贵州茅台",
                    "更新时间": "2026-04-01 18:00:00",
                }
            ],
            "sources_tried": ["stock_irm_cninfo"],
        }

    async def fake_get_social_media_service():
        return fake_service

    async def fake_load_a_share_heat_rows(symbol):
        return {
            "em_latest": [{"item": "当前排名", "value": "3"}],
            "em_realtime": None,
            "em_keywords": None,
            "xq_follow": None,
            "xq_tweet": None,
            "xq_deal": None,
        }

    def fake_normalize_heat_rows_to_messages(symbol, heat_payload):
        return [
            {
                "symbol": symbol,
                "message_id": "heat-1",
                "platform": "eastmoney_guba",
                "message_type": "heat_snapshot",
                "content": "东方财富股吧热度快照：当前排名=3",
                "publish_time": datetime(2026, 4, 2, 12, 0),
                "sentiment": "neutral",
                "sentiment_score": 0.0,
                "author": {"name": "eastmoney_guba", "verified": True},
                "engagement": {},
                "keywords": ["600519"],
                "topics": ["heat"],
                "importance": "medium",
                "credibility": "medium",
                "language": "zh-CN",
                "data_source": "stock_hot_rank_latest_em",
                "crawler_version": "test",
            }
        ]

    async def fake_save_sync_history_record(**kwargs):
        return None

    monkeypatch.setattr(social_sync_service, "_has_existing_social_media_data", fake_has_existing_social_media_data)
    monkeypatch.setattr(social_sync_service, "_load_a_share_native_social_rows", fake_load_a_share_native_social_rows)
    monkeypatch.setattr(social_sync_service, "_load_a_share_heat_rows", fake_load_a_share_heat_rows)
    monkeypatch.setattr(social_sync_service, "_normalize_heat_rows_to_messages", fake_normalize_heat_rows_to_messages)
    monkeypatch.setattr(social_sync_service, "get_social_media_service", fake_get_social_media_service)
    monkeypatch.setattr(social_sync_service, "save_sync_history_record", fake_save_sync_history_record)

    import asyncio

    resolved = asyncio.run(
        social_sync_service.sync_a_share_native_social_media(
            symbol="600519",
            current_user={"id": "test-user"},
            days_back=30,
            max_items=40,
            save_history=True,
            skip_if_existing=False,
            allow_news_fallback=True,
        )
    )

    assert resolved.source == "a_share_native_social"
    assert resolved.saved_messages == 3
    assert resolved.generated_messages == 3
    assert resolved.fallback_used is False
    assert "stock_irm_cninfo" in (resolved.source_details or [])
    assert "stock_hot_rank_latest_em" in (resolved.source_details or [])
    assert fake_service.saved_payload is not None
    assert {item["message_type"] for item in fake_service.saved_payload} == {
        "investor_question",
        "company_answer",
        "heat_snapshot",
    }


def test_sync_a_share_native_social_media_falls_back_to_news_proxy(monkeypatch):
    async def fake_has_existing_social_media_data(symbol, hours_back):
        return {"recent_count": 0, "latest_publish_time": None}

    async def fake_load_a_share_native_social_rows(symbol, max_items):
        return {
            "source": None,
            "rows": [],
            "sources_tried": ["stock_sns_sseinfo", "stock_irm_cninfo"],
        }

    class _FakeProxyResult:
        symbol = "600519"
        source = "stock_news_proxy"
        total_news = 5
        generated_messages = 3
        saved_messages = 3
        failed_messages = 0
        latest_publish_time = datetime(2026, 4, 3, 9, 0)
        used_existing_social_data = False

    async def fake_sync_social_media_from_news_proxy(**kwargs):
        return _FakeProxyResult()

    async def fake_save_sync_history_record(**kwargs):
        return None

    monkeypatch.setattr(social_sync_service, "_has_existing_social_media_data", fake_has_existing_social_media_data)
    monkeypatch.setattr(social_sync_service, "_load_a_share_native_social_rows", fake_load_a_share_native_social_rows)
    monkeypatch.setattr(social_sync_service, "_load_a_share_heat_rows", lambda symbol: _async_result({}))
    monkeypatch.setattr(social_sync_service, "sync_social_media_from_news_proxy", fake_sync_social_media_from_news_proxy)
    monkeypatch.setattr(social_sync_service, "save_sync_history_record", fake_save_sync_history_record)

    import asyncio

    resolved = asyncio.run(
        social_sync_service.sync_a_share_native_social_media(
            symbol="600519",
            current_user={"id": "test-user"},
            save_history=True,
            skip_if_existing=False,
            allow_news_fallback=True,
        )
    )

    assert resolved.saved_messages == 3
    assert resolved.fallback_used is True
    assert resolved.fallback_source == "stock_news_proxy"
    assert resolved.source == "stock_news_proxy"


def test_sync_a_share_native_social_media_succeeds_with_heat_only(monkeypatch):
    fake_service = _FakeSocialService()

    async def fake_has_existing_social_media_data(symbol, hours_back):
        return {"recent_count": 0, "latest_publish_time": None}

    async def fake_load_a_share_native_social_rows(symbol, max_items):
        return {
            "source": None,
            "rows": [],
            "sources_tried": ["stock_sns_sseinfo", "stock_irm_cninfo"],
        }

    async def fake_load_a_share_heat_rows(symbol):
        return {
            "em_latest": {"payload": True},
            "em_realtime": None,
            "em_keywords": None,
            "xq_follow": {"payload": True},
            "xq_tweet": None,
            "xq_deal": None,
        }

    def fake_normalize_heat_rows_to_messages(symbol, heat_payload):
        return [
            {
                "symbol": symbol,
                "message_id": "heat-1",
                "platform": "eastmoney_guba",
                "message_type": "heat_snapshot",
                "content": "东方财富股吧热度快照：当前排名=5",
                "publish_time": datetime(2026, 4, 2, 12, 0),
                "sentiment": "neutral",
                "sentiment_score": 0.0,
                "author": {"name": "eastmoney_guba", "verified": True},
                "engagement": {},
                "keywords": ["600519"],
                "topics": ["heat"],
                "importance": "medium",
                "credibility": "medium",
                "language": "zh-CN",
                "data_source": "stock_hot_rank_latest_em",
                "crawler_version": "test",
            }
        ]

    async def fake_get_social_media_service():
        return fake_service

    async def fake_save_sync_history_record(**kwargs):
        return None

    monkeypatch.setattr(social_sync_service, "_has_existing_social_media_data", fake_has_existing_social_media_data)
    monkeypatch.setattr(social_sync_service, "_load_a_share_native_social_rows", fake_load_a_share_native_social_rows)
    monkeypatch.setattr(social_sync_service, "_load_a_share_heat_rows", fake_load_a_share_heat_rows)
    monkeypatch.setattr(social_sync_service, "_normalize_heat_rows_to_messages", fake_normalize_heat_rows_to_messages)
    monkeypatch.setattr(social_sync_service, "get_social_media_service", fake_get_social_media_service)
    monkeypatch.setattr(social_sync_service, "save_sync_history_record", fake_save_sync_history_record)

    import asyncio

    resolved = asyncio.run(
        social_sync_service.sync_a_share_native_social_media(
            symbol="600519",
            current_user={"id": "test-user"},
            save_history=True,
            skip_if_existing=False,
            allow_news_fallback=True,
        )
    )

    assert resolved.source == "a_share_native_social"
    assert resolved.saved_messages == 1
    assert resolved.generated_messages == 1
    assert resolved.fallback_used is False
    assert "stock_hot_rank_latest_em" in (resolved.source_details or [])
    assert "stock_hot_follow_xq" in (resolved.source_details or [])
    assert fake_service.saved_payload[0]["platform"] == "eastmoney_guba"


async def _async_result(value):
    return value
