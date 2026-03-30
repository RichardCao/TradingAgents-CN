import pytest

from tradingagents.dataflows import interface


def test_indicator_window_supports_comma_separated_indicators(monkeypatch):
    calls = []

    def fake_get_stockstats_indicator(symbol, indicator, curr_date, online):
        calls.append((symbol, indicator, curr_date, online))
        return f"{indicator}-{curr_date}"

    monkeypatch.setattr(interface, "get_stockstats_indicator", fake_get_stockstats_indicator)

    result = interface.get_stock_stats_indicators_window(
        symbol="AAPL",
        indicator="rsi, macd, rsi",
        curr_date="2026-03-10",
        look_back_days=1,
        online=True,
    )

    assert "## rsi values from 2026-03-09 to 2026-03-10" in result
    assert "## macd values from 2026-03-09 to 2026-03-10" in result
    assert result.count("## rsi values from 2026-03-09 to 2026-03-10") == 1

    assert calls == [
        ("AAPL", "rsi", "2026-03-10", True),
        ("AAPL", "rsi", "2026-03-09", True),
        ("AAPL", "macd", "2026-03-10", True),
        ("AAPL", "macd", "2026-03-09", True),
    ]


def test_indicator_window_rejects_unsupported_indicator_in_list():
    with pytest.raises(ValueError, match="Unsupported indicators"):
        interface.get_stock_stats_indicators_window(
            symbol="AAPL",
            indicator="rsi, not_real_indicator",
            curr_date="2026-03-10",
            look_back_days=1,
            online=True,
        )
