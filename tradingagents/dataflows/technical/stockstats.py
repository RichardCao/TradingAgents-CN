import pandas as pd
import yfinance as yf
from stockstats import wrap
from typing import Annotated
import os
from tradingagents.config.config_manager import config_manager


PRICE_NUMERIC_COLUMNS = ("Open", "High", "Low", "Close", "Adj Close", "Volume")

def get_config():
    """兼容性包装函数"""
    return config_manager.load_settings()


def load_price_csv(path: str) -> pd.DataFrame:
    """Load cached price CSVs defensively to tolerate bad rows and NaN-like values."""
    try:
        data = pd.read_csv(
            path,
            on_bad_lines="skip",
            encoding_errors="ignore",
            low_memory=False,
        )
    except TypeError:
        data = pd.read_csv(path, on_bad_lines="skip", low_memory=False)

    if data.empty:
        raise ValueError(f"Price CSV is empty: {path}")

    if "Date" not in data.columns:
        raise ValueError(f"Price CSV missing required 'Date' column: {path}")

    data = data.copy()
    data["Date"] = pd.to_datetime(data["Date"], errors="coerce")
    data = data.dropna(subset=["Date"]).sort_values("Date").reset_index(drop=True)

    if data.empty:
        raise ValueError(f"Price CSV does not contain any valid dated rows: {path}")

    for column in PRICE_NUMERIC_COLUMNS:
        if column in data.columns:
            data[column] = pd.to_numeric(data[column], errors="coerce")

    return data


class StockstatsUtils:
    @staticmethod
    def get_stock_stats(
        symbol: Annotated[str, "ticker symbol for the company"],
        indicator: Annotated[
            str, "quantitative indicators based off of the stock data for the company"
        ],
        curr_date: Annotated[
            str, "curr date for retrieving stock price data, YYYY-mm-dd"
        ],
        data_dir: Annotated[
            str,
            "directory where the stock data is stored.",
        ],
        online: Annotated[
            bool,
            "whether to use online tools to fetch data or offline tools. If True, will use online tools.",
        ] = False,
    ):
        df = None
        data = None

        if not online:
            try:
                data = load_price_csv(
                    os.path.join(
                        data_dir,
                        f"{symbol}-YFin-data-2015-01-01-2025-03-25.csv",
                    )
                )
                df = wrap(data)
            except FileNotFoundError:
                raise Exception("Stockstats fail: Yahoo Finance data not fetched yet!")
        else:
            # Get today's date as YYYY-mm-dd to add to cache
            today_date = pd.Timestamp.today()
            curr_date = pd.to_datetime(curr_date)

            end_date = today_date
            start_date = today_date - pd.DateOffset(years=15)
            start_date = start_date.strftime("%Y-%m-%d")
            end_date = end_date.strftime("%Y-%m-%d")

            # Get config and ensure cache directory exists
            config = get_config()
            os.makedirs(config["data_cache_dir"], exist_ok=True)

            data_file = os.path.join(
                config["data_cache_dir"],
                f"{symbol}-YFin-data-{start_date}-{end_date}.csv",
            )

            if os.path.exists(data_file):
                data = load_price_csv(data_file)
            else:
                data = yf.download(
                    symbol,
                    start=start_date,
                    end=end_date,
                    multi_level_index=False,
                    progress=False,
                    auto_adjust=True,
                )
                data = data.reset_index()
                data.to_csv(data_file, index=False)

            df = wrap(data)
            df["Date"] = df["Date"].dt.strftime("%Y-%m-%d")
            curr_date = curr_date.strftime("%Y-%m-%d")

        df[indicator]  # trigger stockstats to calculate the indicator
        matching_rows = df[df["Date"].str.startswith(curr_date)]

        if not matching_rows.empty:
            indicator_value = matching_rows[indicator].values[0]
            if pd.isna(indicator_value):
                return "N/A: Indicator unavailable due to insufficient or malformed data"
            return indicator_value
        else:
            return "N/A: Not a trading day (weekend or holiday)"
