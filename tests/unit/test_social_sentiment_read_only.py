from datetime import datetime

import tradingagents.agents.utils.agent_utils as agent_utils
from tradingagents.agents.analysts.social_media_analyst import (
    _is_presync_required_sentiment_message,
)


class _FakeCursor:
    def __init__(self, docs):
        self._docs = list(docs)

    def sort(self, field, direction):
        reverse = direction == -1
        self._docs.sort(key=lambda item: item.get(field) or datetime.min, reverse=reverse)
        return self

    def limit(self, value):
        self._docs = self._docs[:value]
        return self

    def __iter__(self):
        return iter(self._docs)


class _FakeCollection:
    def __init__(self, docs):
        self._docs = docs

    def find(self, query):
        symbol_query = query.get("symbol", {})
        symbols = set(symbol_query.get("$in", []))
        publish_time_query = query.get("publish_time")

        result = []
        for doc in self._docs:
            if symbols and doc.get("symbol") not in symbols:
                continue
            publish_time = doc.get("publish_time")
            if publish_time_query:
                if publish_time < publish_time_query["$gte"] or publish_time >= publish_time_query["$lt"]:
                    continue
            result.append(doc)
        return _FakeCursor(result)


class _FakeDB:
    def __init__(self, docs):
        self.social_media_messages = _FakeCollection(docs)


def test_social_sentiment_reads_synced_messages(monkeypatch):
    docs = [
        {
            "symbol": "600519",
            "platform": "cninfo_irm",
            "message_type": "company_answer",
            "data_source": "stock_irm_cninfo",
            "content": "公司表示今年会继续重视股东回报。",
            "publish_time": datetime(2026, 4, 2, 10, 30),
            "sentiment": "positive",
            "sentiment_score": 0.6,
        },
        {
            "symbol": "600519",
            "platform": "eastmoney_guba",
            "message_type": "heat_snapshot",
            "data_source": "stock_hot_rank_latest_em",
            "content": "东方财富股吧热度快照：排名=3；热度=88。",
            "publish_time": datetime(2026, 4, 2, 9, 15),
            "sentiment": "neutral",
            "sentiment_score": 0.0,
        },
        {
            "symbol": "600519",
            "platform": "news_proxy",
            "message_type": "news_sentiment_proxy",
            "data_source": "stock_news_proxy",
            "content": "券商认为公司高端产品景气度仍在延续。",
            "publish_time": datetime(2026, 4, 1, 16, 0),
            "sentiment": "positive",
            "sentiment_score": 0.3,
        },
        {
            "symbol": "600519",
            "platform": "xueqiu",
            "message_type": "heat_snapshot",
            "data_source": "stock_hot_tweet_xq",
            "content": "也有部分观点担心估值偏高，短线波动会加大。",
            "publish_time": datetime(2026, 4, 1, 14, 0),
            "sentiment": "neutral",
            "sentiment_score": 0.1,
        },
    ]

    monkeypatch.setattr(agent_utils, "get_mongo_db_sync", lambda: _FakeDB(docs), raising=False)

    # helper 内部是局部 import，需要补到 app.core.database 上
    import app.core.database as database_module

    monkeypatch.setattr(database_module, "get_mongo_db_sync", lambda: _FakeDB(docs))

    result = agent_utils._get_social_media_sentiment_from_database(
        ticker="600519",
        curr_date="2026-04-03",
        market_info={"market_name": "A股", "is_china": True, "is_hk": False, "is_us": False},
    )

    assert "social_media_messages" in result
    assert "样本数量" in result
    assert "## 官方互动问答" in result
    assert "## 社区热度快照" in result
    assert "## 新闻回退摘录" in result
    assert "cninfo_irm 1条" in result
    assert "eastmoney_guba 1条" in result
    assert "news_proxy 1条" in result
    assert "xueqiu 1条" in result
    assert "来源分布" in result
    assert "stock_irm_cninfo 1条" in result
    assert "stock_hot_rank_latest_em 1条" in result
    assert "stock_news_proxy 1条" in result
    assert "官方互动问答: 1 条" in result
    assert "社区热度: 2 条" in result
    assert "新闻回退: 1 条" in result
    assert "原生社媒样本: 3 条" in result
    assert "参与情绪统计样本: 2 条" in result
    assert "正向: 2 条" in result
    assert "中性: 0 条" in result


def test_social_sentiment_warns_when_a_share_only_has_news_proxy(monkeypatch):
    docs = [
        {
            "symbol": "600519",
            "platform": "news_proxy",
            "message_type": "news_sentiment_proxy",
            "data_source": "stock_news_proxy",
            "content": "公司短期仍受渠道补库存影响，市场分歧加大。",
            "publish_time": datetime(2026, 4, 2, 10, 30),
            "sentiment": "neutral",
            "sentiment_score": 0.0,
        }
    ]

    monkeypatch.setattr(agent_utils, "get_mongo_db_sync", lambda: _FakeDB(docs), raising=False)

    import app.core.database as database_module

    monkeypatch.setattr(database_module, "get_mongo_db_sync", lambda: _FakeDB(docs))

    result = agent_utils._get_social_media_sentiment_from_database(
        ticker="600519",
        curr_date="2026-04-03",
        market_info={"market_name": "A股", "is_china": True, "is_hk": False, "is_us": False},
    )

    assert "原生社媒样本: 0 条" in result
    assert "当前样本主要来自新闻回退" in result


def test_social_sentiment_missing_data_message():
    message = (
        "❌ 未找到 A股 600519 的已同步社媒数据。\n\n"
        "当前社媒分析链路已切换为“优先使用已同步数据，分析阶段只读”。\n"
        "请先通过社媒数据导入或保存接口写入数据后，再重新发起分析。"
    )

    assert _is_presync_required_sentiment_message(message) is True
