"""Shared yfinance client helpers with lightweight retry/backoff."""

from __future__ import annotations

import logging
import time
from typing import Any, Callable

import yfinance as yf

from tradingagents.config.runtime_settings import get_float, get_int

logger = logging.getLogger(__name__)

_TRANSIENT_ERROR_KEYWORDS = (
    "rate limited",
    "too many requests",
    "timed out",
    "timeout",
    "temporarily unavailable",
    "connection aborted",
    "connection reset",
    "remote end closed connection",
    "service unavailable",
    "bad gateway",
    "gateway timeout",
    "http error 429",
)

_INVALID_SYMBOL_KEYWORDS = (
    "possibly delisted",
    "no timezone found",
    "invalid ticker",
    "not found",
    "404",
)


def _default_max_retries() -> int:
    return get_int("TA_YFINANCE_MAX_RETRIES", "ta_yfinance_max_retries", 3)


def _default_base_delay() -> float:
    return get_float(
        "TA_YFINANCE_BASE_DELAY_SECONDS",
        "ta_yfinance_base_delay_seconds",
        1.0,
    )


def _default_max_delay() -> float:
    return get_float(
        "TA_YFINANCE_MAX_DELAY_SECONDS",
        "ta_yfinance_max_delay_seconds",
        8.0,
    )


def is_rate_limit_error(exc: Exception) -> bool:
    message = str(exc).lower()
    return "rate limited" in message or "too many requests" in message or "http error 429" in message


def is_transient_yfinance_error(exc: Exception) -> bool:
    message = str(exc).lower()
    if not message:
        return True

    if any(keyword in message for keyword in _INVALID_SYMBOL_KEYWORDS):
        return False

    return any(keyword in message for keyword in _TRANSIENT_ERROR_KEYWORDS)


def call_with_retry(
    symbol: str,
    operation_name: str,
    operation: Callable[[Any], Any],
    *,
    market: str | None = None,
    max_retries: int | None = None,
    base_delay: float | None = None,
    max_delay: float | None = None,
    rate_limit_delay: float | None = None,
) -> Any:
    """Run a yfinance operation with bounded retry/backoff for transient errors."""
    retry_limit = max(1, max_retries or _default_max_retries())
    retry_base_delay = max(0.0, base_delay if base_delay is not None else _default_base_delay())
    retry_max_delay = max(retry_base_delay, max_delay if max_delay is not None else _default_max_delay())

    last_error: Exception | None = None

    for attempt in range(1, retry_limit + 1):
        ticker = yf.Ticker(symbol)
        try:
            return operation(ticker)
        except Exception as exc:
            last_error = exc
            transient = is_transient_yfinance_error(exc)
            should_retry = transient and attempt < retry_limit
            backoff_seconds = None

            if should_retry:
                if is_rate_limit_error(exc) and rate_limit_delay is not None:
                    backoff_seconds = max(0.0, rate_limit_delay)
                else:
                    backoff_seconds = min(retry_base_delay * (2 ** (attempt - 1)), retry_max_delay)

            logger.warning(
                "yfinance %s failed (symbol=%s, market=%s, attempt=%s/%s, transient=%s, backoff_seconds=%s): %s",
                operation_name,
                symbol,
                market,
                attempt,
                retry_limit,
                transient,
                backoff_seconds,
                exc,
            )

            if not should_retry:
                raise

            time.sleep(backoff_seconds or 0.0)

    if last_error is not None:
        raise last_error

    raise RuntimeError(f"yfinance {operation_name} failed without a captured exception")


def get_ticker_info(
    symbol: str,
    *,
    market: str | None = None,
    max_retries: int | None = None,
    base_delay: float | None = None,
    max_delay: float | None = None,
    rate_limit_delay: float | None = None,
) -> dict[str, Any]:
    return call_with_retry(
        symbol,
        "info",
        lambda ticker: ticker.info,
        market=market,
        max_retries=max_retries,
        base_delay=base_delay,
        max_delay=max_delay,
        rate_limit_delay=rate_limit_delay,
    )


def get_ticker_history(
    symbol: str,
    *,
    market: str | None = None,
    max_retries: int | None = None,
    base_delay: float | None = None,
    max_delay: float | None = None,
    rate_limit_delay: float | None = None,
    **history_kwargs: Any,
) -> Any:
    return call_with_retry(
        symbol,
        "history",
        lambda ticker: ticker.history(**history_kwargs),
        market=market,
        max_retries=max_retries,
        base_delay=base_delay,
        max_delay=max_delay,
        rate_limit_delay=rate_limit_delay,
    )

