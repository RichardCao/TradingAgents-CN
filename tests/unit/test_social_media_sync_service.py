from datetime import datetime

import pandas as pd

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
    assert resolved.summary["sections"]["news_fallback"] == 1
    assert resolved.summary["details"]["news_proxy_messages"] == 1


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
    assert resolved.summary["sections"]["official_ir"] == 2
    assert resolved.summary["sections"]["community_heat"] == 1
    assert resolved.summary["details"]["investor_questions"] == 1
    assert resolved.summary["details"]["company_answers"] == 1
    assert resolved.summary["details"]["heat_snapshots"] == 1
    assert fake_service.saved_payload is not None
    assert {item["message_type"] for item in fake_service.saved_payload} == {
        "investor_question",
        "company_answer",
        "heat_snapshot",
    }


def test_sync_a_share_native_social_media_does_not_fall_back_to_news_proxy(monkeypatch):
    async def fake_has_existing_social_media_data(symbol, hours_back):
        return {"recent_count": 0, "latest_publish_time": None}

    async def fake_load_a_share_native_social_rows(symbol, max_items):
        return {
            "source": None,
            "rows": [],
            "sources_tried": ["stock_sns_sseinfo", "stock_irm_cninfo"],
        }

    async def fake_save_sync_history_record(**kwargs):
        return None

    monkeypatch.setattr(social_sync_service, "_has_existing_social_media_data", fake_has_existing_social_media_data)
    monkeypatch.setattr(social_sync_service, "_load_a_share_native_social_rows", fake_load_a_share_native_social_rows)
    monkeypatch.setattr(social_sync_service, "_load_a_share_heat_rows", lambda symbol: _async_result({}))
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

    assert resolved.saved_messages == 0
    assert resolved.generated_messages == 0
    assert resolved.fallback_used is False
    assert resolved.fallback_source is None
    assert resolved.source == "a_share_native_social"


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
    assert resolved.summary["sections"]["community_heat"] == 1
    assert resolved.summary["details"]["heat_snapshots"] == 1
    assert fake_service.saved_payload[0]["platform"] == "eastmoney_guba"


def test_sync_a_share_native_social_media_aggregates_multiple_official_sources(monkeypatch):
    fake_service = _FakeSocialService()

    async def fake_has_existing_social_media_data(symbol, hours_back):
        return {"recent_count": 0, "latest_publish_time": None}

    async def fake_load_a_share_native_social_rows(symbol, max_items):
        return {
            "source": "stock_sns_sseinfo",
            "rows": [
                {
                    "公司简称": "测试公司",
                    "问题": "旧兼容字段，不应单独使用",
                }
            ],
            "sources_tried": ["stock_sns_sseinfo", "stock_irm_cninfo"],
            "source_results": [
                {
                    "source": "stock_sns_sseinfo",
                    "rows": [
                        {
                            "股票代码": "600519",
                            "公司简称": "贵州茅台",
                            "用户名": "投资者A",
                            "问题时间": "2026-04-01 09:00:00",
                            "问题": "请问渠道库存情况如何？",
                            "回答时间": "2026-04-01 11:00:00",
                            "回答": "公司会结合经营情况稳步推进渠道管理。",
                            "回答来源": "贵州茅台",
                        }
                    ],
                },
                {
                    "source": "stock_irm_cninfo",
                    "rows": [
                        {
                            "公司简称": "贵州茅台",
                            "问题": "请问今年分红规划如何？",
                            "提问者": "价值投资者",
                            "提问时间": "2026-04-02 10:00:00",
                            "问题编号": "q-002",
                            "回答ID": "a-002",
                            "回答内容": "公司将综合经营情况审慎制定分红方案。",
                            "回答者": "贵州茅台",
                            "更新时间": "2026-04-02 18:00:00",
                        }
                    ],
                },
            ],
        }

    async def fake_load_a_share_heat_rows(symbol):
        return {}

    async def fake_get_social_media_service():
        return fake_service

    async def fake_save_sync_history_record(**kwargs):
        return None

    monkeypatch.setattr(social_sync_service, "_has_existing_social_media_data", fake_has_existing_social_media_data)
    monkeypatch.setattr(social_sync_service, "_load_a_share_native_social_rows", fake_load_a_share_native_social_rows)
    monkeypatch.setattr(social_sync_service, "_load_a_share_heat_rows", fake_load_a_share_heat_rows)
    monkeypatch.setattr(social_sync_service, "get_social_media_service", fake_get_social_media_service)
    monkeypatch.setattr(social_sync_service, "save_sync_history_record", fake_save_sync_history_record)

    import asyncio

    resolved = asyncio.run(
        social_sync_service.sync_a_share_native_social_media(
            symbol="600519",
            current_user={"id": "test-user"},
            save_history=True,
            skip_if_existing=False,
            allow_news_fallback=False,
        )
    )

    assert resolved.source == "a_share_native_social"
    assert resolved.saved_messages == 4
    assert resolved.generated_messages == 4
    assert resolved.total_source_items == 2
    assert resolved.fallback_used is False
    assert resolved.source_details == ["stock_sns_sseinfo", "stock_irm_cninfo"]
    assert resolved.summary["sections"]["official_ir"] == 4
    assert resolved.summary["details"]["investor_questions"] == 2
    assert resolved.summary["details"]["company_answers"] == 2
    assert fake_service.saved_payload is not None
    assert {item["platform"] for item in fake_service.saved_payload} == {"sse_einteractive", "cninfo_irm"}


def test_normalize_heat_rows_to_messages_includes_relate_up_and_baidu_sources():
    heat_payload = {
        "em_rank": {
            "代码": "SH600519",
            "股票名称": "贵州茅台",
            "当前排名": 3,
            "最新价": 1688.0,
            "涨跌幅": 2.31,
        },
        "em_detail": pd.DataFrame(
            [
                {"时间": "2026-04-05", "排名": 8, "证券代码": "SH600519", "新晋粉丝": 0.11, "铁杆粉丝": 0.22},
                {"时间": "2026-04-07", "排名": 3, "证券代码": "SH600519", "新晋粉丝": 0.15, "铁杆粉丝": 0.28},
            ]
        ),
        "em_relate": [
            {
                "时间": "2026-04-07 09:30:00",
                "股票代码": "SH600519",
                "相关股票代码": "000858",
                "涨跌幅": 1.86,
            },
            {
                "时间": "2026-04-07 09:30:00",
                "股票代码": "SH600519",
                "相关股票代码": "600036",
                "涨跌幅": -0.42,
            },
        ],
        "em_up": {
            "代码": "SH600519",
            "当前排名": 6,
            "排名较昨日变动": 12,
            "最新价": 1688.0,
            "涨跌幅": 2.31,
        },
        "baidu_search": {
            "名称/代码": "贵州茅台 600519",
            "综合热度": 987654,
            "涨跌幅": "+2.31%",
        },
    }

    messages = social_sync_service._normalize_heat_rows_to_messages("600519", heat_payload)
    source_details = social_sync_service._collect_heat_source_details(heat_payload)

    assert {item["data_source"] for item in messages} == {
        "stock_hot_rank_em",
        "stock_hot_rank_detail_em",
        "stock_hot_rank_relate_em",
        "stock_hot_up_em",
        "stock_hot_search_baidu",
    }
    assert {item["platform"] for item in messages} == {
        "eastmoney_guba",
        "baidu_gushitong",
    }
    assert {item["message_type"] for item in messages} == {"keyword_snapshot", "heat_snapshot"}
    assert source_details == [
        "stock_hot_rank_em",
        "stock_hot_rank_detail_em",
        "stock_hot_rank_relate_em",
        "stock_hot_up_em",
        "stock_hot_search_baidu",
    ]


def test_enrich_cninfo_rows_with_answer_details_backfills_missing_answer(monkeypatch):
    async def fake_fetch_cninfo_answer_detail(question_id):
        assert question_id == "q-100"
        return {
            "股票代码": "600519",
            "公司简称": "贵州茅台",
            "问题": "请问今年直营渠道规划如何？",
            "回答内容": "公司会结合市场需求持续优化直营网点布局。",
            "提问者": "价值投资者",
            "提问时间": "2026-04-06 09:00:00",
            "回答时间": "2026-04-06 18:00:00",
        }

    monkeypatch.setattr(social_sync_service, "_fetch_cninfo_answer_detail", fake_fetch_cninfo_answer_detail)

    import asyncio

    rows = asyncio.run(
        social_sync_service._enrich_cninfo_rows_with_answer_details(
            [
                {
                    "股票代码": "600519",
                    "公司简称": "贵州茅台",
                    "问题编号": "q-100",
                    "问题": "请问今年直营渠道规划如何？",
                    "提问者": "价值投资者",
                    "提问时间": "2026-04-06 09:00:00",
                    "回答内容": "",
                    "回答者": "",
                }
            ]
        )
    )

    assert rows[0]["回答内容"] == "公司会结合市场需求持续优化直营网点布局。"
    assert rows[0]["回答者"] == "贵州茅台"
    assert rows[0]["回答时间"] == "2026-04-06 18:00:00"
    assert rows[0]["__used_answer_detail_source"] is True


def test_sync_a_share_native_social_media_marks_cninfo_answer_detail_source(monkeypatch):
    fake_service = _FakeSocialService()

    async def fake_has_existing_social_media_data(symbol, hours_back):
        return {"recent_count": 0, "latest_publish_time": None}

    async def fake_load_a_share_native_social_rows(symbol, max_items):
        return {
            "source": "stock_irm_cninfo",
            "rows": [
                {
                    "股票代码": "600519",
                    "公司简称": "贵州茅台",
                    "问题编号": "q-200",
                    "问题": "请问直营渠道如何布局？",
                    "提问者": "投资者A",
                    "提问时间": "2026-04-06 09:00:00",
                    "回答内容": "",
                    "回答者": "",
                    "__used_answer_detail_source": True,
                }
            ],
            "sources_tried": ["stock_irm_cninfo"],
            "source_results": [
                {
                    "source": "stock_irm_cninfo",
                    "rows": [
                        {
                            "股票代码": "600519",
                            "公司简称": "贵州茅台",
                            "问题编号": "q-200",
                            "问题": "请问直营渠道如何布局？",
                            "提问者": "投资者A",
                            "提问时间": "2026-04-06 09:00:00",
                            "回答内容": "公司会结合市场需求稳步推进直营网点布局。",
                            "回答者": "贵州茅台",
                            "__used_answer_detail_source": True,
                        }
                    ],
                }
            ],
        }

    async def fake_load_a_share_heat_rows(symbol):
        return {}

    async def fake_get_social_media_service():
        return fake_service

    async def fake_save_sync_history_record(**kwargs):
        return None

    monkeypatch.setattr(social_sync_service, "_has_existing_social_media_data", fake_has_existing_social_media_data)
    monkeypatch.setattr(social_sync_service, "_load_a_share_native_social_rows", fake_load_a_share_native_social_rows)
    monkeypatch.setattr(social_sync_service, "_load_a_share_heat_rows", fake_load_a_share_heat_rows)
    monkeypatch.setattr(social_sync_service, "get_social_media_service", fake_get_social_media_service)
    monkeypatch.setattr(social_sync_service, "save_sync_history_record", fake_save_sync_history_record)

    import asyncio

    resolved = asyncio.run(
        social_sync_service.sync_a_share_native_social_media(
            symbol="600519",
            current_user={"id": "test-user"},
            save_history=True,
            skip_if_existing=False,
            allow_news_fallback=False,
        )
    )

    assert "stock_irm_cninfo" in (resolved.source_details or [])
    assert "stock_irm_ans_cninfo" in (resolved.source_details or [])


async def _async_result(value):
    return value
