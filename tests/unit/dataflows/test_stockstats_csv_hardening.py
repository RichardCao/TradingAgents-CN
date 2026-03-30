import pandas as pd

from tradingagents.dataflows.technical import stockstats as stockstats_module


def test_load_price_csv_skips_bad_rows_and_coerces_nan(tmp_path):
    csv_path = tmp_path / "AAPL-YFin-data-2015-01-01-2025-03-25.csv"
    csv_path.write_text(
        "\n".join(
            [
                "Date,Open,High,Low,Close,Volume",
                "2025-03-20,100,101,99,100,1000",
                "bad,row,with,too,many,fields,ignored",
                "2025-03-21,101,102,100,not-a-number,1100",
                "2025-03-22,102,103,101,102,1200",
            ]
        ),
        encoding="utf-8",
    )

    data = stockstats_module.load_price_csv(str(csv_path))

    assert list(data["Date"].dt.strftime("%Y-%m-%d")) == [
        "2025-03-20",
        "2025-03-21",
        "2025-03-22",
    ]
    assert pd.isna(data.loc[1, "Close"])


def test_get_stock_stats_returns_friendly_message_when_indicator_is_nan(monkeypatch):
    wrapped = pd.DataFrame(
        {
            "Date": ["2025-03-25"],
            "close_10_ema": [float("nan")],
        }
    )

    monkeypatch.setattr(
        stockstats_module,
        "load_price_csv",
        lambda path: pd.DataFrame({"Date": ["2025-03-25"], "Close": [100.0]}),
    )
    monkeypatch.setattr(stockstats_module, "wrap", lambda data: wrapped.copy())

    result = stockstats_module.StockstatsUtils.get_stock_stats(
        symbol="AAPL",
        indicator="close_10_ema",
        curr_date="2025-03-25",
        data_dir="/tmp",
        online=False,
    )

    assert result == "N/A: Indicator unavailable due to insufficient or malformed data"
