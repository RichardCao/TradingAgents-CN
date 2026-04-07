"""
QuotesService: 提供A股批量实时快照获取（AKShare东方财富 spot 接口），带内存TTL缓存。
- 不使用通达信（TDX）作为兜底数据源。
- 在小批量缺口场景下可回退到独立 sina_finance provider。
- 仅用于筛选返回前对 items 进行行情富集。
"""
from __future__ import annotations

import asyncio
import os
import time
import logging
from datetime import datetime, timedelta, timezone
from typing import Any, Dict, List, Optional

logger = logging.getLogger(__name__)

QuoteSnapshot = Dict[str, Any]


def _safe_float(v) -> Optional[float]:
    try:
        if v is None:
            return None
        # 处理字符串中的逗号/百分号/空白
        if isinstance(v, str):
            s = v.strip().replace(",", "")
            if s.endswith("%"):
                s = s[:-1]
            if s == "-" or s == "":
                return None
            return float(s)
        # 处理 pandas/numpy 数值
        return float(v)
    except Exception:
        return None


class QuotesService:
    def __init__(self, ttl_seconds: int = 30) -> None:
        self._ttl = ttl_seconds
        self._cache_ts: float = 0.0
        self._cache: Dict[str, QuoteSnapshot] = {}
        self._lock = asyncio.Lock()
        self._sina_finance_fallback_enabled = self._read_sina_fallback_enabled()
        self._sina_finance_fallback_max_symbols = self._read_sina_fallback_max_symbols()

    def _read_sina_fallback_enabled(self) -> bool:
        raw_value = str(
            os.getenv("TRADINGAGENTS_ENABLE_SINA_FINANCE_FALLBACK", "true")
        ).strip().lower()
        return raw_value not in {"0", "false", "no", "off"}

    def _read_sina_fallback_max_symbols(self) -> int:
        raw_value = os.getenv("TRADINGAGENTS_SINA_FINANCE_FALLBACK_MAX_SYMBOLS", "20")
        try:
            return max(0, int(str(raw_value).strip()))
        except Exception:
            return 20

    def _should_use_sina_finance_fallback(self, symbol_count: int) -> bool:
        if not self._sina_finance_fallback_enabled:
            return False
        if symbol_count <= 0:
            return False
        return symbol_count <= self._sina_finance_fallback_max_symbols

    async def get_quotes(self, codes: List[str]) -> Dict[str, QuoteSnapshot]:
        """获取一批股票的近实时快照（最新价、涨跌幅、成交额）。
        - 优先使用缓存；缓存超时或为空则刷新一次全市场快照。
        - 返回仅包含请求的 codes。
        """
        codes = list(dict.fromkeys([c.strip() for c in codes if c]))
        now = time.time()
        async with self._lock:
            if self._cache and (now - self._cache_ts) < self._ttl:
                return {c: q for c, q in self._cache.items() if c in codes and q}
            # 刷新缓存（阻塞IO放到线程）
            data = await asyncio.to_thread(self._fetch_spot_akshare, codes)
            self._cache = data
            self._cache_ts = time.time()
            return {c: q for c, q in self._cache.items() if c in codes and q}

    def _fetch_sina_finance_quotes(
        self, codes: List[str]
    ) -> Dict[str, QuoteSnapshot]:
        if not self._should_use_sina_finance_fallback(len(codes)):
            if self._sina_finance_fallback_enabled:
                logger.info(
                    "ℹ️ 跳过 sina_finance 兜底：请求股票数 %s 超过上限 %s",
                    len(codes),
                    self._sina_finance_fallback_max_symbols,
                )
            else:
                logger.info("ℹ️ 已禁用 sina_finance 兜底")
            return {}

        from tradingagents.dataflows.providers.sina_finance import SinaFinanceQuoteClient

        client = SinaFinanceQuoteClient(timeout=8)
        raw_quotes = client.fetch_quotes(codes, market_hint="CN")
        results: Dict[str, QuoteSnapshot] = {}

        for code in codes:
            quote = raw_quotes.get(code)
            if not quote:
                continue
            results[code] = {
                "close": quote.current_price,
                "pct_chg": quote.change_percent,
                "amount": quote.amount,
                "trade_date": quote.trade_date,
                "updated_at": quote.updated_at,
                "data_source": quote.source,
            }

        if results:
            logger.info("✅ 使用独立 sina_finance 兜底补齐 %s 只股票行情", len(results))
        return results

    def _build_realtime_meta(self) -> Dict[str, str]:
        cn_tz = timezone(timedelta(hours=8))
        now_cn = datetime.now(cn_tz)
        return {
            "trade_date": now_cn.strftime("%Y-%m-%d"),
            "updated_at": now_cn.isoformat(),
        }

    def _normalize_akshare_row(
        self,
        code: str,
        row: Any,
        *,
        price_col: str,
        pct_col: Optional[str],
        amount_col: Optional[str],
        realtime_meta: Dict[str, str],
    ) -> QuoteSnapshot:
        return {
            "close": _safe_float(row.get(price_col)),
            "pct_chg": _safe_float(row.get(pct_col)) if pct_col else None,
            "amount": _safe_float(row.get(amount_col)) if amount_col else None,
            "trade_date": realtime_meta["trade_date"],
            "updated_at": realtime_meta["updated_at"],
            "data_source": "akshare_eastmoney",
        }

    def _fetch_spot_akshare(self, requested_codes: List[str]) -> Dict[str, QuoteSnapshot]:
        """通过 AKShare 东方财富全市场快照接口拉取行情，并标准化为字典。
        预期列（常见）：代码、名称、最新价、涨跌幅、成交额。
        不同版本可能有差异，做多列名兼容。
        对小批量缺口可回退到独立 sina_finance provider。
        """
        requested_codes = list(dict.fromkeys([str(code).strip() for code in requested_codes if code]))
        realtime_meta = self._build_realtime_meta()
        try:
            import akshare as ak  # 已在项目中使用，不额外安装
            df = ak.stock_zh_a_spot_em()
            if df is None or getattr(df, "empty", True):
                logger.warning("AKShare spot 返回空数据")
                return self._fetch_sina_finance_quotes(requested_codes)
            # 兼容常见列名
            code_col = next((c for c in ["代码", "代码code", "symbol", "股票代码"] if c in df.columns), None)
            price_col = next((c for c in ["最新价", "现价", "最新价(元)", "price", "最新"] if c in df.columns), None)
            pct_col = next((c for c in ["涨跌幅", "涨跌幅(%)", "涨幅", "pct_chg"] if c in df.columns), None)
            amount_col = next((c for c in ["成交额", "成交额(元)", "amount", "成交额(万元)"] if c in df.columns), None)

            if not code_col or not price_col:
                logger.error(f"AKShare spot 缺少必要列: code={code_col}, price={price_col}")
                return self._fetch_sina_finance_quotes(requested_codes)

            result: Dict[str, QuoteSnapshot] = {}
            for _, row in df.iterrows():  # type: ignore
                code_raw = row.get(code_col)
                if not code_raw:
                    continue
                # 标准化股票代码：移除前导0，然后补齐到6位
                code_str = str(code_raw).strip()
                # 如果是纯数字，移除前导0后补齐到6位
                if code_str.isdigit():
                    code_clean = code_str.lstrip('0') or '0'  # 移除前导0，如果全是0则保留一个0
                    code = code_clean.zfill(6)  # 补齐到6位
                else:
                    code = code_str.zfill(6)
                result[code] = self._normalize_akshare_row(
                    code,
                    row,
                    price_col=price_col,
                    pct_col=pct_col,
                    amount_col=amount_col,
                    realtime_meta=realtime_meta,
                )

            missing_codes = [code for code in requested_codes if code not in result]
            if missing_codes:
                result.update(self._fetch_sina_finance_quotes(missing_codes))
            logger.info(f"AKShare spot 拉取完成: {len(result)} 条")
            return result
        except Exception as e:
            logger.error(f"获取AKShare实时快照失败: {e}")
            return self._fetch_sina_finance_quotes(requested_codes)


_quotes_service: Optional[QuotesService] = None


def get_quotes_service() -> QuotesService:
    global _quotes_service
    if _quotes_service is None:
        _quotes_service = QuotesService(ttl_seconds=30)
    return _quotes_service
