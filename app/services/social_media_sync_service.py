"""
社媒同步服务

当前支持两类同步方式：

1. A 股原生社媒同步
   - 优先使用官方互动问答数据
   - 沪市优先上证 e 互动
   - 深市/北交所优先巨潮互动易
2. 新闻代理同步
   - 从已同步新闻生成“舆情快照”
   - 作为低成本 fallback
"""

from __future__ import annotations

import asyncio
import hashlib
from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import Any, Dict, List, Optional
import re

from app.core.database import get_mongo_db
from app.services.social_media_service import get_social_media_service
from app.routers.stock_sync import save_sync_history_record
from tradingagents.utils.stock_utils import StockUtils


@dataclass
class SocialMediaSyncResult:
    symbol: str
    source: str
    total_news: int
    generated_messages: int
    saved_messages: int
    failed_messages: int
    total_source_items: int = 0
    skipped_existing: bool = False
    used_existing_social_data: bool = False
    latest_publish_time: Optional[datetime] = None
    source_details: Optional[List[str]] = None
    fallback_used: bool = False
    fallback_source: Optional[str] = None
    summary: Optional[Dict[str, Any]] = None


def _build_news_proxy_message_id(symbol: str, news_doc: Dict[str, Any]) -> str:
    raw = "|".join(
        [
            symbol,
            str(news_doc.get("title", "") or ""),
            str(news_doc.get("url", "") or ""),
            str(news_doc.get("publish_time", "") or ""),
        ]
    )
    digest = hashlib.sha1(raw.encode("utf-8")).hexdigest()
    return f"news-proxy-{digest}"


def _build_native_message_id(
    symbol: str,
    *,
    platform: str,
    message_type: str,
    source: str,
    unique_value: str,
) -> str:
    raw = "|".join([symbol, platform, message_type, source, unique_value])
    digest = hashlib.sha1(raw.encode("utf-8")).hexdigest()
    return f"native-social-{digest}"


def _clean_text(value: Any) -> str:
    text = str(value or "").strip()
    text = re.sub(r"\s+", " ", text)
    return text


def _coerce_datetime(value: Any) -> Optional[datetime]:
    if isinstance(value, datetime):
        return value
    if value in (None, ""):
        return None

    text = str(value).strip()
    if not text:
        return None

    normalized = text.replace("/", "-")
    for candidate in (normalized, normalized.replace("T", " ")):
        try:
            return datetime.fromisoformat(candidate)
        except Exception:
            continue

    for fmt in ("%Y-%m-%d %H:%M:%S", "%Y-%m-%d"):
        try:
            return datetime.strptime(normalized, fmt)
        except Exception:
            continue

    return None


def _build_native_message(
    *,
    symbol: str,
    platform: str,
    message_type: str,
    content: str,
    publish_time: Optional[datetime],
    author_name: str,
    verified: bool,
    data_source: str,
    unique_value: str,
    importance: str = "medium",
    keywords: Optional[List[str]] = None,
) -> Optional[Dict[str, Any]]:
    normalized_content = _clean_text(content)
    if not normalized_content:
        return None

    publish_dt = publish_time or datetime.utcnow()
    return {
        "symbol": symbol,
        "message_id": _build_native_message_id(
            symbol,
            platform=platform,
            message_type=message_type,
            source=data_source,
            unique_value=unique_value,
        ),
        "platform": platform,
        "message_type": message_type,
        "content": normalized_content,
        "media_urls": [],
        "hashtags": [],
        "author": {
            "name": _clean_text(author_name) or ("上市公司" if verified else "投资者"),
            "verified": verified,
            "influence_score": 0.8 if verified else 0.35,
        },
        "engagement": {
            "views": 0,
            "likes": 0,
            "shares": 0,
            "comments": 0,
            "engagement_rate": 0.0,
        },
        "publish_time": publish_dt,
        "sentiment": "neutral",
        "sentiment_score": 0.0,
        "keywords": keywords or [],
        "topics": ["investor_relations"],
        "importance": importance,
        "credibility": "high" if verified else "medium",
        "location": None,
        "language": "zh-CN",
        "data_source": data_source,
        "crawler_version": "a-share-native-v1",
    }


def _normalize_cninfo_rows_to_messages(symbol: str, rows: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    messages: List[Dict[str, Any]] = []
    for row in rows:
        question_id = str(row.get("问题编号") or row.get("提问者编号") or row.get("提问时间") or "")
        question_time = _coerce_datetime(row.get("提问时间"))
        answer_time = _coerce_datetime(row.get("更新时间")) or _coerce_datetime(row.get("回答时间"))
        company_name = _clean_text(row.get("公司简称"))
        keywords = [item for item in [symbol, company_name] if item]

        question_message = _build_native_message(
            symbol=symbol,
            platform="cninfo_irm",
            message_type="investor_question",
            content=row.get("问题"),
            publish_time=question_time,
            author_name=str(row.get("提问者") or "投资者"),
            verified=False,
            data_source="stock_irm_cninfo",
            unique_value=f"q|{question_id}|{row.get('问题', '')}",
            importance="medium",
            keywords=keywords,
        )
        if question_message:
            messages.append(question_message)

        answer_content = row.get("回答内容")
        answer_message = _build_native_message(
            symbol=symbol,
            platform="cninfo_irm",
            message_type="company_answer",
            content=answer_content,
            publish_time=answer_time or question_time,
            author_name=str(row.get("回答者") or company_name or "上市公司"),
            verified=True,
            data_source="stock_irm_cninfo",
            unique_value=f"a|{row.get('回答ID') or question_id}|{answer_content or ''}",
            importance="high",
            keywords=keywords,
        )
        if answer_message:
            messages.append(answer_message)

    return messages


def _normalize_sse_rows_to_messages(symbol: str, rows: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    messages: List[Dict[str, Any]] = []
    for row in rows:
        question_time = _coerce_datetime(row.get("问题时间"))
        answer_time = _coerce_datetime(row.get("回答时间"))
        company_name = _clean_text(row.get("公司简称"))
        user_name = _clean_text(row.get("用户名")) or "投资者"
        keywords = [item for item in [symbol, company_name] if item]
        base_id = "|".join(
            [
                str(row.get("股票代码") or symbol),
                str(row.get("问题时间") or ""),
                str(row.get("问题") or ""),
            ]
        )

        question_message = _build_native_message(
            symbol=symbol,
            platform="sse_einteractive",
            message_type="investor_question",
            content=row.get("问题"),
            publish_time=question_time,
            author_name=user_name,
            verified=False,
            data_source="stock_sns_sseinfo",
            unique_value=f"q|{base_id}",
            importance="medium",
            keywords=keywords,
        )
        if question_message:
            messages.append(question_message)

        answer_content = row.get("回答")
        answer_message = _build_native_message(
            symbol=symbol,
            platform="sse_einteractive",
            message_type="company_answer",
            content=answer_content,
            publish_time=answer_time or question_time,
            author_name=str(row.get("回答来源") or company_name or "上市公司"),
            verified=True,
            data_source="stock_sns_sseinfo",
            unique_value=f"a|{base_id}|{answer_content or ''}",
            importance="high",
            keywords=keywords,
        )
        if answer_message:
            messages.append(answer_message)

    return messages


def _resolve_a_share_native_sources(symbol: str) -> List[str]:
    market_info = StockUtils.get_market_info(symbol)
    exchange_code = str(market_info.get("exchange_code") or "").upper()
    if exchange_code == "SSE":
        return ["stock_sns_sseinfo", "stock_irm_cninfo"]
    return ["stock_irm_cninfo"]


def _normalize_code_digits(value: Any, width: int = 6) -> str:
    digits = "".join(ch for ch in str(value or "") if ch.isdigit())
    if not digits:
        return ""
    return digits[-width:].zfill(width)


def _build_a_share_prefixed_symbol(symbol: str) -> str:
    symbol6 = StockUtils.normalize_display_symbol(symbol).zfill(6)
    market_info = StockUtils.get_market_info(symbol6)
    exchange_code = str(market_info.get("exchange_code") or "").upper()
    prefix_map = {
        "SSE": "SH",
        "SZSE": "SZ",
        "BSE": "BJ",
    }
    return f"{prefix_map.get(exchange_code, 'SZ')}{symbol6}"


def _build_heat_message(
    *,
    symbol: str,
    platform: str,
    message_type: str,
    data_source: str,
    content: str,
    unique_value: str,
    publish_time: Optional[datetime] = None,
    keywords: Optional[List[str]] = None,
) -> Optional[Dict[str, Any]]:
    return _build_native_message(
        symbol=symbol,
        platform=platform,
        message_type=message_type,
        content=content,
        publish_time=publish_time or datetime.utcnow(),
        author_name=platform,
        verified=True,
        data_source=data_source,
        unique_value=unique_value,
        importance="medium",
        keywords=keywords,
    )


def _to_record_list(value: Any) -> List[Dict[str, Any]]:
    if value is None:
        return []
    if isinstance(value, list):
        return [item for item in value if isinstance(item, dict)]
    if isinstance(value, dict):
        return [value]
    if hasattr(value, "to_dict"):
        try:
            records = value.to_dict("records")
            if isinstance(records, list):
                return [item for item in records if isinstance(item, dict)]
        except Exception:
            return []
    return []


def _extract_symbol_from_text(value: Any) -> str:
    digits = "".join(ch for ch in str(value or "") if ch.isdigit())
    if len(digits) >= 6:
        return digits[-6:]
    return ""


def _extract_symbol_hit(records: List[Dict[str, Any]], symbol6: str, candidate_fields: List[str]) -> Optional[Dict[str, Any]]:
    for row in records:
        for field in candidate_fields:
            row_symbol = _extract_symbol_from_text(row.get(field))
            if row_symbol == symbol6:
                return row
    return None


async def _load_a_share_heat_rows(symbol: str) -> Dict[str, Any]:
    symbol6 = StockUtils.normalize_display_symbol(symbol).zfill(6)
    prefixed_symbol = _build_a_share_prefixed_symbol(symbol6)

    import akshare as ak

    results: Dict[str, Any] = {}

    async def _run_to_thread(func, *args, **kwargs):
        return await asyncio.to_thread(func, *args, **kwargs)

    try:
        em_rank_df = await _run_to_thread(ak.stock_hot_rank_em)
        results["em_rank"] = _extract_symbol_hit(
            _to_record_list(em_rank_df),
            symbol6,
            ["代码", "股票代码", "名称/代码"],
        )
    except Exception:
        results["em_rank"] = None

    try:
        results["em_detail"] = await _run_to_thread(ak.stock_hot_rank_detail_em, symbol=prefixed_symbol)
    except Exception:
        results["em_detail"] = None

    try:
        results["em_latest"] = await _run_to_thread(ak.stock_hot_rank_latest_em, symbol=prefixed_symbol)
    except Exception:
        results["em_latest"] = None

    try:
        results["em_realtime"] = await _run_to_thread(ak.stock_hot_rank_detail_realtime_em, symbol=prefixed_symbol)
    except Exception:
        results["em_realtime"] = None

    try:
        results["em_keywords"] = await _run_to_thread(ak.stock_hot_keyword_em, symbol=prefixed_symbol)
    except Exception:
        results["em_keywords"] = None

    try:
        results["em_relate"] = await _run_to_thread(ak.stock_hot_rank_relate_em, symbol=prefixed_symbol)
    except Exception:
        results["em_relate"] = None

    def _extract_xq_hit(df: Any) -> Optional[Dict[str, Any]]:
        if df is None or getattr(df, "empty", True):
            return None
        working = df.reset_index(drop=True).copy()
        working["_rank"] = working.index + 1
        for _, row in working.iterrows():
            row_code = _normalize_code_digits(row.get("股票代码"))
            if row_code == symbol6:
                return row.to_dict()
        return None

    try:
        results["xq_follow"] = _extract_xq_hit(await _run_to_thread(ak.stock_hot_follow_xq, symbol="最热门"))
    except Exception:
        results["xq_follow"] = None

    try:
        results["xq_tweet"] = _extract_xq_hit(await _run_to_thread(ak.stock_hot_tweet_xq, symbol="最热门"))
    except Exception:
        results["xq_tweet"] = None

    try:
        results["xq_deal"] = _extract_xq_hit(await _run_to_thread(ak.stock_hot_deal_xq, symbol="最热门"))
    except Exception:
        results["xq_deal"] = None

    try:
        em_up_df = await _run_to_thread(ak.stock_hot_up_em)
        results["em_up"] = _extract_symbol_hit(
            _to_record_list(em_up_df),
            symbol6,
            ["代码", "股票代码", "名称/代码"],
        )
    except Exception:
        results["em_up"] = None

    try:
        baidu_df = await _run_to_thread(
            ak.stock_hot_search_baidu,
            symbol="A股",
            date=datetime.now().strftime("%Y%m%d"),
            time="今日",
        )
        results["baidu_search"] = _extract_symbol_hit(
            _to_record_list(baidu_df),
            symbol6,
            ["名称/代码", "代码", "股票代码"],
        )
    except Exception:
        results["baidu_search"] = None

    return results


def _normalize_heat_rows_to_messages(symbol: str, heat_payload: Dict[str, Any]) -> List[Dict[str, Any]]:
    messages: List[Dict[str, Any]] = []
    symbol6 = StockUtils.normalize_display_symbol(symbol).zfill(6)
    market_info = StockUtils.get_market_info(symbol6)
    company_hint = market_info.get("display_symbol") or symbol6
    keywords = [symbol6, str(company_hint)]
    now = datetime.utcnow()

    em_latest = heat_payload.get("em_latest")
    if em_latest is not None and not getattr(em_latest, "empty", True):
        pairs = em_latest.to_dict("records")
        summary = "；".join(
            f"{str(item.get('item') or '').strip()}={str(item.get('value') or '').strip()}"
            for item in pairs[:6]
            if str(item.get("item") or "").strip()
        )
        if summary:
            msg = _build_heat_message(
                symbol=symbol6,
                platform="eastmoney_guba",
                message_type="heat_snapshot",
                data_source="stock_hot_rank_latest_em",
                content=f"东方财富股吧热度快照：{summary}",
                unique_value=f"em_latest|{summary}",
                publish_time=now,
                keywords=keywords,
            )
            if msg:
                messages.append(msg)

    em_rank_row = heat_payload.get("em_rank")
    if em_rank_row:
        content = (
            f"东方财富人气总榜：当前排名 {em_rank_row.get('当前排名')}，"
            f"股票名称 {em_rank_row.get('股票名称')}，"
            f"最新价 {em_rank_row.get('最新价')}，涨跌幅 {em_rank_row.get('涨跌幅')}%。"
        )
        msg = _build_heat_message(
            symbol=symbol6,
            platform="eastmoney_guba",
            message_type="heat_snapshot",
            data_source="stock_hot_rank_em",
            content=content,
            unique_value=(
                f"em_rank|{em_rank_row.get('当前排名')}|"
                f"{em_rank_row.get('最新价')}|{em_rank_row.get('涨跌幅')}"
            ),
            publish_time=now,
            keywords=keywords,
        )
        if msg:
            messages.append(msg)

    em_detail = heat_payload.get("em_detail")
    if em_detail is not None and not getattr(em_detail, "empty", True):
        detail_records = em_detail.to_dict("records")
        if detail_records:
            latest = detail_records[-1]
            earliest = detail_records[0]
            content = (
                f"东方财富人气历史趋势：最新时间 {latest.get('时间')} 排名 {latest.get('排名')}，"
                f"新晋粉丝占比 {latest.get('新晋粉丝')}，铁杆粉丝占比 {latest.get('铁杆粉丝')}；"
                f"起点时间 {earliest.get('时间')} 排名 {earliest.get('排名')}。"
            )
            msg = _build_heat_message(
                symbol=symbol6,
                platform="eastmoney_guba",
                message_type="heat_snapshot",
                data_source="stock_hot_rank_detail_em",
                content=content,
                unique_value=(
                    f"em_detail|{latest.get('时间')}|{latest.get('排名')}|"
                    f"{latest.get('新晋粉丝')}|{latest.get('铁杆粉丝')}"
                ),
                publish_time=_coerce_datetime(latest.get("时间")) or now,
                keywords=keywords,
            )
            if msg:
                messages.append(msg)

    em_realtime = heat_payload.get("em_realtime")
    if em_realtime is not None and not getattr(em_realtime, "empty", True):
        records = em_realtime.to_dict("records")
        if records:
            latest = records[-1]
            earliest = records[0]
            content = (
                f"东方财富股吧实时热度：最新时间 {latest.get('时间')} 排名 {latest.get('排名')}；"
                f"区间起点 {earliest.get('时间')} 排名 {earliest.get('排名')}。"
            )
            msg = _build_heat_message(
                symbol=symbol6,
                platform="eastmoney_guba",
                message_type="heat_snapshot",
                data_source="stock_hot_rank_detail_realtime_em",
                content=content,
                unique_value=f"em_realtime|{latest.get('时间')}|{latest.get('排名')}",
                publish_time=_coerce_datetime(latest.get("时间")) or now,
                keywords=keywords,
            )
            if msg:
                messages.append(msg)

    em_keywords = heat_payload.get("em_keywords")
    if em_keywords is not None and not getattr(em_keywords, "empty", True):
        keyword_records = em_keywords.to_dict("records")
        top_keywords = [
            f"{str(item.get('概念名称') or '').strip()}({str(item.get('热度') or '').strip()})"
            for item in keyword_records[:5]
            if str(item.get("概念名称") or "").strip()
        ]
        if top_keywords:
            msg = _build_heat_message(
                symbol=symbol6,
                platform="eastmoney_guba",
                message_type="keyword_snapshot",
                data_source="stock_hot_keyword_em",
                content=f"东方财富股吧热门关键词：{'、'.join(top_keywords)}",
                unique_value=f"em_keyword|{'|'.join(top_keywords)}",
                publish_time=now,
                keywords=keywords + top_keywords[:3],
            )
            if msg:
                messages.append(msg)

    em_relate_records = _to_record_list(heat_payload.get("em_relate"))
    if em_relate_records:
        related_rows = em_relate_records[:5]
        related_summary = "；".join(
            f"{_extract_symbol_from_text(item.get('相关股票代码')) or item.get('相关股票代码')}({item.get('涨跌幅')}%)"
            for item in related_rows
            if item.get("相关股票代码") is not None
        )
        if related_summary:
            msg = _build_heat_message(
                symbol=symbol6,
                platform="eastmoney_guba",
                message_type="keyword_snapshot",
                data_source="stock_hot_rank_relate_em",
                content=f"东方财富相关股票联动：{related_summary}",
                unique_value=f"em_relate|{related_summary}",
                publish_time=_coerce_datetime(related_rows[0].get("时间")) or now,
                keywords=keywords,
            )
            if msg:
                messages.append(msg)

    xq_metric_map = {
        "xq_follow": ("stock_hot_follow_xq", "雪球关注热度"),
        "xq_tweet": ("stock_hot_tweet_xq", "雪球讨论热度"),
        "xq_deal": ("stock_hot_deal_xq", "雪球交易分享热度"),
    }
    for key, (source_name, label) in xq_metric_map.items():
        row = heat_payload.get(key)
        if not row:
            continue
        rank = row.get("_rank")
        metric_value = row.get("关注")
        price_value = row.get("最新价")
        row_symbol = row.get("股票代码")
        content = (
            f"{label}：代码 {row_symbol} 排名 {rank}，热度值 {metric_value}，最新价 {price_value}。"
        )
        msg = _build_heat_message(
            symbol=symbol6,
            platform="xueqiu",
            message_type="heat_snapshot",
            data_source=source_name,
            content=content,
            unique_value=f"{source_name}|{rank}|{metric_value}|{price_value}",
            publish_time=now,
            keywords=keywords,
        )
        if msg:
            messages.append(msg)

    em_up_row = heat_payload.get("em_up")
    if em_up_row:
        content = (
            f"东方财富飙升榜：当前排名 {em_up_row.get('当前排名')}，"
            f"较昨日变动 {em_up_row.get('排名较昨日变动')}，"
            f"最新价 {em_up_row.get('最新价')}，涨跌幅 {em_up_row.get('涨跌幅')}%。"
        )
        msg = _build_heat_message(
            symbol=symbol6,
            platform="eastmoney_guba",
            message_type="heat_snapshot",
            data_source="stock_hot_up_em",
            content=content,
            unique_value=(
                f"em_up|{em_up_row.get('当前排名')}|"
                f"{em_up_row.get('排名较昨日变动')}|{em_up_row.get('最新价')}"
            ),
            publish_time=now,
            keywords=keywords,
        )
        if msg:
            messages.append(msg)

    baidu_search_row = heat_payload.get("baidu_search")
    if baidu_search_row:
        content = (
            f"百度股市通热搜：名称/代码 {baidu_search_row.get('名称/代码')}，"
            f"综合热度 {baidu_search_row.get('综合热度')}，"
            f"涨跌幅 {baidu_search_row.get('涨跌幅')}。"
        )
        msg = _build_heat_message(
            symbol=symbol6,
            platform="baidu_gushitong",
            message_type="heat_snapshot",
            data_source="stock_hot_search_baidu",
            content=content,
            unique_value=(
                f"baidu_search|{baidu_search_row.get('名称/代码')}|"
                f"{baidu_search_row.get('综合热度')}|{baidu_search_row.get('涨跌幅')}"
            ),
            publish_time=now,
            keywords=keywords,
        )
        if msg:
            messages.append(msg)

    return messages


def _has_heat_payload_content(value: Any) -> bool:
    if value is None:
        return False
    if isinstance(value, dict):
        return bool(value)
    if isinstance(value, (list, tuple, set)):
        return bool(value)
    return not getattr(value, "empty", True)


def _summarize_social_messages(messages: List[Dict[str, Any]]) -> Dict[str, Any]:
    summary = {
        "sections": {
            "official_ir": 0,
            "community_heat": 0,
            "news_fallback": 0,
            "other": 0,
        },
        "details": {
            "investor_questions": 0,
            "company_answers": 0,
            "heat_snapshots": 0,
            "keyword_snapshots": 0,
            "news_proxy_messages": 0,
        },
        "platforms": {},
    }

    for message in messages:
        platform = str(message.get("platform") or "unknown").strip()
        message_type = str(message.get("message_type") or "").strip()

        if platform in {"cninfo_irm", "sse_einteractive"} or message_type in {
            "investor_question",
            "company_answer",
        }:
            summary["sections"]["official_ir"] += 1
        elif platform in {"eastmoney_guba", "xueqiu"} or message_type in {
            "heat_snapshot",
            "keyword_snapshot",
        }:
            summary["sections"]["community_heat"] += 1
        elif platform == "news_proxy" or message_type == "news_sentiment_proxy":
            summary["sections"]["news_fallback"] += 1
        else:
            summary["sections"]["other"] += 1

        if message_type == "investor_question":
            summary["details"]["investor_questions"] += 1
        elif message_type == "company_answer":
            summary["details"]["company_answers"] += 1
        elif message_type == "heat_snapshot":
            summary["details"]["heat_snapshots"] += 1
        elif message_type == "keyword_snapshot":
            summary["details"]["keyword_snapshots"] += 1
        elif message_type == "news_sentiment_proxy":
            summary["details"]["news_proxy_messages"] += 1

        summary["platforms"][platform] = summary["platforms"].get(platform, 0) + 1

    return summary


def _collect_heat_source_details(heat_payload: Dict[str, Any]) -> List[str]:
    source_map = {
        "em_rank": "stock_hot_rank_em",
        "em_detail": "stock_hot_rank_detail_em",
        "em_latest": "stock_hot_rank_latest_em",
        "em_realtime": "stock_hot_rank_detail_realtime_em",
        "em_keywords": "stock_hot_keyword_em",
        "em_relate": "stock_hot_rank_relate_em",
        "em_up": "stock_hot_up_em",
        "xq_follow": "stock_hot_follow_xq",
        "xq_tweet": "stock_hot_tweet_xq",
        "xq_deal": "stock_hot_deal_xq",
        "baidu_search": "stock_hot_search_baidu",
    }
    return [
        source_name
        for key, source_name in source_map.items()
        if _has_heat_payload_content(heat_payload.get(key))
    ]


def _deduplicate_messages(messages: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    deduplicated: List[Dict[str, Any]] = []
    seen: set[tuple[str, str]] = set()

    for message in messages:
        key = (
            str(message.get("message_id") or "").strip(),
            str(message.get("platform") or "").strip(),
        )
        if not key[0] or key in seen:
            continue
        seen.add(key)
        deduplicated.append(message)

    return deduplicated


async def _fetch_native_source_rows(
    symbol: str,
    source_name: str,
    max_items: int,
) -> List[Dict[str, Any]]:
    symbol6 = StockUtils.normalize_display_symbol(symbol).zfill(6)

    if source_name == "stock_irm_cninfo":
        import akshare as ak

        df = await asyncio.to_thread(ak.stock_irm_cninfo, symbol=symbol6)
    elif source_name == "stock_sns_sseinfo":
        import akshare as ak

        df = await asyncio.to_thread(ak.stock_sns_sseinfo, symbol=symbol6)
    else:
        raise ValueError(f"不支持的 A 股原生社媒来源: {source_name}")

    if df is None or getattr(df, "empty", True):
        return []

    rows = df.head(max_items).to_dict("records")
    if source_name == "stock_irm_cninfo":
        rows = await _enrich_cninfo_rows_with_answer_details(rows)
    return rows


async def _fetch_cninfo_answer_detail(question_id: str) -> Dict[str, Any]:
    import akshare as ak

    df = await asyncio.to_thread(ak.stock_irm_ans_cninfo, symbol=question_id)
    if df is None or getattr(df, "empty", True):
        return {}
    records = df.to_dict("records")
    return records[0] if records else {}


async def _enrich_cninfo_rows_with_answer_details(
    rows: List[Dict[str, Any]],
    *,
    max_detail_fetches: int = 5,
) -> List[Dict[str, Any]]:
    enriched_rows: List[Dict[str, Any]] = []
    remaining_fetches = max_detail_fetches

    for row in rows:
        enriched_row = dict(row)
        needs_detail = not _clean_text(enriched_row.get("回答内容"))
        question_id = str(enriched_row.get("问题编号") or "").strip()

        if needs_detail and question_id and remaining_fetches > 0:
            remaining_fetches -= 1
            try:
                detail = await _fetch_cninfo_answer_detail(question_id)
            except Exception:
                detail = {}

            if detail:
                if not _clean_text(enriched_row.get("回答内容")):
                    enriched_row["回答内容"] = detail.get("回答内容") or enriched_row.get("回答内容")
                if not _clean_text(enriched_row.get("回答者")):
                    enriched_row["回答者"] = detail.get("公司简称") or detail.get("回答者") or enriched_row.get("回答者")
                if not _clean_text(enriched_row.get("回答时间")):
                    enriched_row["回答时间"] = detail.get("回答时间") or enriched_row.get("更新时间") or enriched_row.get("回答时间")
                enriched_row["__used_answer_detail_source"] = True

        enriched_rows.append(enriched_row)

    return enriched_rows


async def _load_a_share_native_social_rows(symbol: str, max_items: int) -> Dict[str, Any]:
    sources_tried: List[str] = []
    source_results: List[Dict[str, Any]] = []

    for source_name in _resolve_a_share_native_sources(symbol):
        sources_tried.append(source_name)
        try:
            rows = await _fetch_native_source_rows(symbol, source_name, max_items)
            if rows:
                source_results.append(
                    {
                        "source": source_name,
                        "rows": rows,
                    }
                )
        except Exception:
            continue

    if source_results:
        first_result = source_results[0]
        return {
            "source": first_result.get("source"),
            "rows": first_result.get("rows") or [],
            "sources_tried": sources_tried,
            "source_results": source_results,
        }

    return {
        "source": None,
        "rows": [],
        "sources_tried": sources_tried,
        "source_results": [],
    }


def _normalize_news_to_social_message(symbol: str, news_doc: Dict[str, Any]) -> Dict[str, Any]:
    publish_time = news_doc.get("publish_time")
    if not isinstance(publish_time, datetime):
        publish_time = datetime.utcnow()

    source = str(news_doc.get("source") or "news_proxy")
    content = str(news_doc.get("content") or news_doc.get("summary") or news_doc.get("title") or "").strip()
    title = str(news_doc.get("title") or "").strip()

    return {
        "symbol": symbol,
        "message_id": _build_news_proxy_message_id(symbol, news_doc),
        "platform": "news_proxy",
        "message_type": "news_sentiment_proxy",
        "content": f"{title}\n\n{content}".strip(),
        "media_urls": [],
        "hashtags": news_doc.get("keywords", []) or [],
        "author": {
            "name": source,
            "verified": True,
            "influence_score": 0.5,
        },
        "engagement": {
            "views": 0,
            "likes": 0,
            "shares": 0,
            "comments": 0,
            "engagement_rate": 0.0,
        },
        "publish_time": publish_time,
        "sentiment": str(news_doc.get("sentiment") or "neutral"),
        "sentiment_score": float(news_doc.get("sentiment_score") or 0.0),
        "keywords": news_doc.get("keywords", []) or [],
        "topics": [str(news_doc.get("category") or "news_proxy")],
        "importance": str(news_doc.get("importance") or "medium"),
        "credibility": "medium",
        "location": None,
        "language": str(news_doc.get("language") or "zh-CN"),
        "data_source": "stock_news_proxy",
        "crawler_version": "news-proxy-v1",
    }


async def _load_recent_news_docs(symbol: str, hours_back: int, max_items: int) -> List[Dict[str, Any]]:
    db = get_mongo_db()
    end_dt = datetime.utcnow()
    start_dt = end_dt - timedelta(hours=hours_back)

    query_list = [
        {"symbol": symbol, "publish_time": {"$gte": start_dt, "$lte": end_dt}},
        {"symbols": symbol, "publish_time": {"$gte": start_dt, "$lte": end_dt}},
        {"symbol": symbol},
        {"symbols": symbol},
    ]

    for query in query_list:
        docs = await db.stock_news.find(query).sort("publish_time", -1).to_list(length=max_items)
        if docs:
            return docs[:max_items]

    return []


async def _has_existing_social_media_data(symbol: str, hours_back: int) -> Dict[str, Any]:
    db = get_mongo_db()
    end_dt = datetime.utcnow()
    start_dt = end_dt - timedelta(hours=hours_back)
    recent_query = {
        "symbol": symbol,
        "publish_time": {"$gte": start_dt, "$lte": end_dt},
    }

    recent_count = await db.social_media_messages.count_documents(recent_query)
    latest_doc = await db.social_media_messages.find_one(
        {"symbol": symbol},
        sort=[("publish_time", -1), ("updated_at", -1)],
    )
    return {
        "recent_count": recent_count,
        "latest_publish_time": latest_doc.get("publish_time") if latest_doc else None,
    }


async def sync_social_media_from_news_proxy(
    *,
    symbol: str,
    current_user: Optional[dict] = None,
    hours_back: int = 72,
    max_items: int = 30,
    save_history: bool = True,
    skip_if_existing: bool = True,
) -> SocialMediaSyncResult:
    started_at = datetime.utcnow()
    existing = await _has_existing_social_media_data(symbol, hours_back)

    if skip_if_existing and existing["recent_count"] > 0:
        result = SocialMediaSyncResult(
            symbol=symbol,
            source="stock_news_proxy",
            total_news=0,
            generated_messages=0,
            saved_messages=0,
            failed_messages=0,
            skipped_existing=True,
            used_existing_social_data=True,
            latest_publish_time=existing["latest_publish_time"],
        )
        if save_history and current_user:
            await save_sync_history_record(
                current_user=current_user,
                symbol=symbol,
                sync_types=["social_media"],
                data_source_requested="stock_news_proxy",
                data_sources_used=["stock_news_proxy"],
                status="success",
                overall_success=True,
                summary="社媒数据已存在，跳过重复生成",
                errors=[],
                result={
                    "symbol": symbol,
                    "sync_stats": {
                        "generated_messages": 0,
                        "saved_messages": 0,
                        "failed_messages": 0,
                        "used_existing_social_data": True,
                    }
                },
                started_at=started_at,
                finished_at=datetime.utcnow(),
                historical_range={
                    "start_date": (started_at - timedelta(hours=hours_back)).strftime("%Y-%m-%d"),
                    "end_date": started_at.strftime("%Y-%m-%d"),
                    "days": max(1, (hours_back + 23) // 24),
                },
            )
        return result

    news_docs = await _load_recent_news_docs(symbol, hours_back, max_items)
    messages = [_normalize_news_to_social_message(symbol, doc) for doc in news_docs]

    saved_messages = 0
    failed_messages = 0
    latest_publish_time = None
    if messages:
        latest_publish_time = max(
            (msg["publish_time"] for msg in messages if isinstance(msg.get("publish_time"), datetime)),
            default=None,
        )
        service = await get_social_media_service()
        save_result = await service.save_social_media_messages(messages)
        saved_messages = int(save_result.get("saved", 0))
        failed_messages = int(save_result.get("failed", 0))
    else:
        failed_messages = 0

    finished_at = datetime.utcnow()
    overall_success = saved_messages > 0
    status = "success" if overall_success else "failed"

    result = SocialMediaSyncResult(
        symbol=symbol,
        source="stock_news_proxy",
        total_news=len(news_docs),
        generated_messages=len(messages),
        saved_messages=saved_messages,
        failed_messages=failed_messages,
        latest_publish_time=latest_publish_time,
        summary=_summarize_social_messages(messages),
    )

    if save_history and current_user:
        await save_sync_history_record(
            current_user=current_user,
            symbol=symbol,
            sync_types=["social_media"],
            data_source_requested="stock_news_proxy",
            data_sources_used=["stock_news_proxy"],
            status=status,
            overall_success=overall_success,
            summary=(
                f"从已同步新闻生成舆情快照 {saved_messages} 条成功"
                if overall_success
                else "未能从已同步新闻生成舆情快照"
            ),
            errors=[] if overall_success else ["未找到可转换的已同步新闻数据"],
            result={
                "symbol": symbol,
                "sync_stats": {
                    "total_news": len(news_docs),
                    "generated_messages": len(messages),
                    "saved_messages": saved_messages,
                    "failed_messages": failed_messages,
                    "used_existing_social_data": False,
                    "summary": result.summary,
                }
            },
            started_at=started_at,
            finished_at=finished_at,
            historical_range={
                "start_date": (started_at - timedelta(hours=hours_back)).strftime("%Y-%m-%d"),
                "end_date": started_at.strftime("%Y-%m-%d"),
                "days": max(1, (hours_back + 23) // 24),
            },
        )

    return result


async def sync_a_share_native_social_media(
    *,
    symbol: str,
    current_user: Optional[dict] = None,
    days_back: int = 30,
    max_items: int = 40,
    save_history: bool = True,
    skip_if_existing: bool = True,
    allow_news_fallback: bool = True,
) -> SocialMediaSyncResult:
    started_at = datetime.utcnow()
    existing = await _has_existing_social_media_data(symbol, days_back * 24)

    if skip_if_existing and existing["recent_count"] > 0:
        result = SocialMediaSyncResult(
            symbol=symbol,
            source="a_share_native_social",
            total_news=0,
            generated_messages=0,
            saved_messages=0,
            failed_messages=0,
            total_source_items=0,
            skipped_existing=True,
            used_existing_social_data=True,
            latest_publish_time=existing["latest_publish_time"],
            source_details=[],
        )
        if save_history and current_user:
            await save_sync_history_record(
                current_user=current_user,
                symbol=symbol,
                sync_types=["social_media"],
                data_source_requested="a_share_native_social",
                data_sources_used=[],
                status="success",
                overall_success=True,
                summary="社媒数据已存在，跳过重复生成",
                errors=[],
                result={
                    "symbol": symbol,
                    "sync_stats": {
                        "generated_messages": 0,
                        "saved_messages": 0,
                        "failed_messages": 0,
                        "used_existing_social_data": True,
                    }
                },
                started_at=started_at,
                finished_at=datetime.utcnow(),
                historical_range={
                    "start_date": (started_at - timedelta(days=days_back)).strftime("%Y-%m-%d"),
                    "end_date": started_at.strftime("%Y-%m-%d"),
                    "days": max(1, days_back),
                },
            )
        return result

    native_payload = await _load_a_share_native_social_rows(symbol, max_items)
    source_results = native_payload.get("source_results") or []
    if not source_results and (native_payload.get("source") or native_payload.get("rows")):
        source_results = [
            {
                "source": native_payload.get("source"),
                "rows": native_payload.get("rows") or [],
            }
        ]

    native_messages: List[Dict[str, Any]] = []
    native_source_details: List[str] = []
    native_total_items = 0
    for source_result in source_results:
        native_source = source_result.get("source")
        rows = source_result.get("rows") or []
        if not native_source or not rows:
            continue

        native_total_items += len(rows)
        if native_source == "stock_irm_cninfo":
            native_messages.extend(_normalize_cninfo_rows_to_messages(symbol, rows))
            if any(bool(row.get("__used_answer_detail_source")) for row in rows):
                native_source_details.append("stock_irm_ans_cninfo")
        elif native_source == "stock_sns_sseinfo":
            native_messages.extend(_normalize_sse_rows_to_messages(symbol, rows))

        if native_source not in native_source_details:
            native_source_details.append(native_source)

    heat_payload = await _load_a_share_heat_rows(symbol)
    heat_messages = _normalize_heat_rows_to_messages(symbol, heat_payload)
    heat_source_details = _collect_heat_source_details(heat_payload)

    messages = _deduplicate_messages(native_messages + heat_messages)

    source_details: List[str] = []
    source_details.extend(native_source_details)
    source_details.extend(
        source_name for source_name in heat_source_details if source_name not in source_details
    )

    saved_messages = 0
    failed_messages = 0
    latest_publish_time = None
    if messages:
        latest_publish_time = max(
            (msg["publish_time"] for msg in messages if isinstance(msg.get("publish_time"), datetime)),
            default=None,
        )
        service = await get_social_media_service()
        save_result = await service.save_social_media_messages(messages)
        saved_messages = int(save_result.get("saved", 0))
        failed_messages = int(save_result.get("failed", 0))

    fallback_used = False
    fallback_source = None
    result_source = "a_share_native_social" if len(source_details) > 1 else (
        source_details[0] if source_details else "a_share_native_social"
    )
    total_news = 0
    generated_messages = len(messages)
    total_source_items = native_total_items + len(heat_messages)

    if not messages and allow_news_fallback:
        fallback_result = await sync_social_media_from_news_proxy(
            symbol=symbol,
            current_user=current_user,
            hours_back=max(72, min(days_back * 24, 24 * 30)),
            max_items=max_items,
            save_history=False,
            skip_if_existing=False,
        )
        if fallback_result.saved_messages > 0 or fallback_result.used_existing_social_data:
            fallback_used = True
            fallback_source = fallback_result.source
            result_source = fallback_result.source
            total_news = fallback_result.total_news
            generated_messages = fallback_result.generated_messages
            saved_messages = fallback_result.saved_messages
            failed_messages = fallback_result.failed_messages
            latest_publish_time = fallback_result.latest_publish_time
            source_details = source_details + [fallback_result.source]

    finished_at = datetime.utcnow()
    overall_success = saved_messages > 0 or (skip_if_existing and existing["recent_count"] > 0)
    status = "success" if overall_success else "failed"

    result = SocialMediaSyncResult(
        symbol=symbol,
        source=result_source,
        total_news=total_news,
        generated_messages=generated_messages,
        saved_messages=saved_messages,
        failed_messages=failed_messages,
        total_source_items=total_source_items,
        latest_publish_time=latest_publish_time,
        source_details=source_details,
        fallback_used=fallback_used,
        fallback_source=fallback_source,
        summary=_summarize_social_messages(messages),
    )

    if save_history and current_user:
        await save_sync_history_record(
            current_user=current_user,
            symbol=symbol,
            sync_types=["social_media"],
            data_source_requested="a_share_native_social",
            data_sources_used=source_details,
            status=status,
            overall_success=overall_success,
            summary=(
                f"A股原生社媒同步成功，写入 {saved_messages} 条"
                + (f"（已回退 {fallback_source}）" if fallback_used and fallback_source else "")
                if overall_success
                else "A股原生社媒同步未写入任何数据"
            ),
            errors=[] if overall_success else ["未获取到可用的 A 股原生社媒数据"],
            result={
                "symbol": symbol,
                "sync_stats": {
                    "source": result_source,
                    "source_details": source_details,
                    "total_source_items": total_source_items,
                    "total_news": total_news,
                    "generated_messages": generated_messages,
                    "saved_messages": saved_messages,
                    "failed_messages": failed_messages,
                    "fallback_used": fallback_used,
                    "fallback_source": fallback_source,
                    "summary": result.summary,
                }
            },
            started_at=started_at,
            finished_at=finished_at,
            historical_range={
                "start_date": (started_at - timedelta(days=days_back)).strftime("%Y-%m-%d"),
                "end_date": started_at.strftime("%Y-%m-%d"),
                "days": max(1, days_back),
            },
        )

    return result
