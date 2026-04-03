"""
分析前预同步服务

将分析所需的数据同步动作显式前置到分析开始前，
并复用现有同步接口写入统一同步历史。
"""

from __future__ import annotations

from datetime import datetime, timedelta
from typing import Any, Dict, List, Optional

from fastapi import BackgroundTasks

from app.core.database import get_mongo_db
from app.models.analysis import SingleAnalysisRequest
from app.routers.news_data import sync_single_stock_news
from app.routers.stock_sync import SingleStockSyncRequest, sync_single_stock
from app.services.social_media_sync_service import (
    sync_a_share_native_social_media,
    sync_social_media_from_news_proxy,
)


def _normalize_analysis_date(request: SingleAnalysisRequest) -> str:
    analysis_date = request.parameters.analysis_date if request.parameters else None
    if isinstance(analysis_date, datetime):
        return analysis_date.strftime("%Y-%m-%d")
    if isinstance(analysis_date, str) and analysis_date.strip():
        return analysis_date.strip()[:10]
    return datetime.now().strftime("%Y-%m-%d")


def _resolve_selected_analysts(request: SingleAnalysisRequest) -> List[str]:
    selected = request.parameters.selected_analysts if request.parameters else None
    if not selected:
        return ["market", "fundamentals"]
    return [str(item).strip().lower() for item in selected if str(item).strip()]


def _should_sync_realtime(market_type: str, analysis_date: str, analysts: List[str]) -> bool:
    if market_type not in {"A股", "港股"}:
        return False
    if not {"market", "fundamentals"} & set(analysts):
        return False
    return analysis_date == datetime.now().strftime("%Y-%m-%d")


def _build_stock_sync_request(request: SingleAnalysisRequest) -> Optional[SingleStockSyncRequest]:
    symbol = request.get_symbol().strip().upper()
    market_type = request.parameters.market_type if request.parameters else "A股"
    analysts = _resolve_selected_analysts(request)
    analysis_date = _normalize_analysis_date(request)

    if market_type == "美股":
        return None

    sync_historical = "market" in analysts or "fundamentals" in analysts
    sync_financial = "fundamentals" in analysts
    sync_basic = True
    sync_realtime = _should_sync_realtime(market_type, analysis_date, analysts)

    if market_type == "A股":
        data_source = "mixed" if sync_realtime else "tushare"
    else:
        # 当前仓库的港股分析更多依赖 AKShare/港股专用 provider，
        # 不强制走 A 股财务同步链路，避免把可运行分析提前阻断。
        sync_financial = False
        data_source = "akshare"
        if sync_realtime and not sync_historical and not sync_financial and not sync_basic:
            data_source = "akshare"

    return SingleStockSyncRequest(
        symbol=symbol,
        sync_realtime=sync_realtime,
        sync_historical=sync_historical,
        sync_financial=sync_financial,
        sync_basic=sync_basic,
        data_source=data_source,
        days=365,
    )


async def _check_existing_social_media_data(
    *,
    symbol: str,
    analysis_date: str,
) -> Dict[str, Any]:
    db = get_mongo_db()
    end_dt = datetime.strptime(analysis_date, "%Y-%m-%d")
    end_dt = end_dt.replace(hour=23, minute=59, second=59)
    start_dt = end_dt.replace(hour=0, minute=0, second=0) - timedelta(days=7)

    recent_query = {
        "symbol": symbol,
        "publish_time": {"$gte": start_dt, "$lte": end_dt},
    }
    recent_count = await db.social_media_messages.count_documents(recent_query)

    latest_doc = await db.social_media_messages.find_one(
        {"symbol": symbol},
        sort=[("publish_time", -1), ("updated_at", -1)],
    )

    if recent_count > 0:
        return {
            "success": True,
            "message": f"已找到最近 7 天内的社媒数据，共 {recent_count} 条",
            "data": {
                "recent_count": recent_count,
                "latest_publish_time": latest_doc.get("publish_time") if latest_doc else None,
            },
        }

    if latest_doc:
        return {
            "success": True,
            "message": "最近 7 天内无社媒数据，已回退到历史已同步数据",
            "data": {
                "recent_count": 0,
                "latest_publish_time": latest_doc.get("publish_time"),
            },
        }

    return {
        "success": False,
        "message": "未找到已同步社媒数据，请先导入或保存社媒消息后再分析",
        "data": {
            "recent_count": 0,
            "latest_publish_time": None,
        },
    }


async def run_analysis_pre_sync(
    *,
    current_user: dict,
    request: SingleAnalysisRequest,
) -> Dict[str, Any]:
    """
    按分析所需数据执行预同步，并返回可直接挂到错误详情中的结果。
    """
    symbol = request.get_symbol().strip().upper()
    market_type = request.parameters.market_type if request.parameters else "A股"
    analysts = _resolve_selected_analysts(request)
    analysis_date = _normalize_analysis_date(request)

    summary: Dict[str, Any] = {
        "symbol": symbol,
        "market_type": market_type,
        "analysis_date": analysis_date,
        "selected_analysts": analysts,
        "steps": [],
        "overall_success": True,
    }

    stock_sync_request = _build_stock_sync_request(request)
    if stock_sync_request is not None and any(
        [
            stock_sync_request.sync_realtime,
            stock_sync_request.sync_historical,
            stock_sync_request.sync_financial,
            stock_sync_request.sync_basic,
        ]
    ):
        stock_sync_response = await sync_single_stock(
            request=stock_sync_request,
            background_tasks=BackgroundTasks(),
            current_user=current_user,
        )
        stock_sync_success = bool(stock_sync_response.get("success"))
        stock_sync_data = stock_sync_response.get("data") or {}
        summary["steps"].append(
            {
                "type": "market_data",
                "success": stock_sync_success and bool(stock_sync_data.get("overall_success")),
                "message": stock_sync_response.get("message"),
                "data": stock_sync_data,
            }
        )
        if not stock_sync_success or not stock_sync_data.get("overall_success"):
            summary["overall_success"] = False

    if "news" in analysts and market_type == "A股":
        news_response = await sync_single_stock_news(
            symbol=symbol,
            data_sources=["akshare", "realtime"],
            hours_back=72,
            max_news_per_source=30,
            current_user=current_user,
        )
        news_success = bool(news_response.get("success"))
        news_data = news_response.get("data") or {}
        sync_stats = news_data.get("sync_stats") or {}
        summary["steps"].append(
            {
                "type": "news",
                "success": news_success and sync_stats.get("successful_saves", 0) > 0,
                "message": news_response.get("message"),
                "data": news_data,
            }
        )
        if not news_success or sync_stats.get("successful_saves", 0) <= 0:
            summary["overall_success"] = False

    if "social" in analysts:
        social_check = await _check_existing_social_media_data(symbol=symbol, analysis_date=analysis_date)
        if not social_check.get("success") and market_type == "A股":
            social_sync_result = await sync_a_share_native_social_media(
                symbol=symbol,
                current_user=current_user,
                days_back=30,
                max_items=40,
                save_history=True,
                skip_if_existing=True,
                allow_news_fallback=True,
            )
            if social_sync_result.saved_messages > 0 or social_sync_result.used_existing_social_data:
                social_check = {
                    "success": True,
                    "message": (
                        f"已同步 A 股社媒数据，来源: {social_sync_result.source}"
                        if social_sync_result.saved_messages > 0
                        else "已存在可用社媒数据"
                    ),
                    "data": {
                        "source": social_sync_result.source,
                        "source_details": social_sync_result.source_details,
                        "generated_messages": social_sync_result.generated_messages,
                        "saved_messages": social_sync_result.saved_messages,
                        "used_existing_social_data": social_sync_result.used_existing_social_data,
                        "fallback_used": social_sync_result.fallback_used,
                        "fallback_source": social_sync_result.fallback_source,
                        "latest_publish_time": social_sync_result.latest_publish_time,
                    },
                }

        summary["steps"].append(
            {
                "type": "social_media",
                "success": bool(social_check.get("success")),
                "message": social_check.get("message"),
                "data": social_check.get("data") or {},
            }
        )
        if not social_check.get("success"):
            summary["overall_success"] = False

    return summary
