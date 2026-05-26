import logging
import time
from datetime import datetime, timedelta
from typing import List, Optional

import pandas as pd
import yfinance as yf

from models import Bar, FundamentalData

logger = logging.getLogger(__name__)


class YFinanceLoader:
    """Data loader backed by yfinance."""

    name = "yfinance"

    def fetch_historical(
        self,
        ticker: str,
        start: str = "",
        end: str = "",
        interval: str = "1d",
        auto_adjust: bool = True,
    ) -> List[Bar]:
        """Fetch historical bars for a ticker.

        Args:
            ticker: Stock ticker symbol.
            start: Start date (YYYY-MM-DD). Defaults to 1 year before end.
            end: End date (YYYY-MM-DD). Defaults to yesterday.
            interval: Data interval (e.g. "1d", "1wk", "1mo").
            auto_adjust: Adjust prices for splits and dividends.

        Returns:
            List of standardized Bar objects.
        """
        # Resolve default date range
        if not end:
            end_dt = datetime.now() - timedelta(days=1)
            end = end_dt.strftime("%Y-%m-%d")
        if not start:
            end_dt = datetime.strptime(end, "%Y-%m-%d")
            start_dt = end_dt - timedelta(days=365)
            start = start_dt.strftime("%Y-%m-%d")

        try:
            df = yf.Ticker(ticker).history(
                start=start,
                end=end,
                interval=interval,
                auto_adjust=auto_adjust,
            )
        except Exception as exc:
            logger.warning("yfinance history fetch failed for %s: %s", ticker, exc)
            return []

        if df.empty:
            return []

        bars: List[Bar] = []
        for idx, row in df.iterrows():
            date_str = idx.strftime("%Y-%m-%d") if isinstance(idx, datetime) else str(idx)
            bars.append(
                Bar(
                    date=date_str,
                    open=0.0 if pd.isna(row.get("Open")) else float(row["Open"]),
                    high=0.0 if pd.isna(row.get("High")) else float(row["High"]),
                    low=0.0 if pd.isna(row.get("Low")) else float(row["Low"]),
                    close=0.0 if pd.isna(row.get("Close")) else float(row["Close"]),
                    volume=0 if pd.isna(row.get("Volume")) else int(row["Volume"]),
                    wap=0.0,
                    count=0,
                )
            )

        return bars

    def fetch_fundamental(self, ticker: str) -> Optional[FundamentalData]:
        """Fetch fundamental data for a ticker.

        Args:
            ticker: Stock ticker symbol.

        Returns:
            FundamentalData if available, otherwise None.
        """
        try:
            info = yf.Ticker(ticker).info
        except Exception as exc:
            logger.warning("yfinance info fetch failed for %s: %s", ticker, exc)
            return None

        if not info:
            return None

        # dividendYield comes as a ratio (e.g. 0.0054); keep as-is
        dividend_yield = info.get("dividendYield")
        if dividend_yield is not None and pd.isna(dividend_yield):
            dividend_yield = None

        return FundamentalData(
            ticker=ticker,
            market_cap=info.get("marketCap"),
            pe_ratio=info.get("trailingPE"),
            pb_ratio=info.get("priceToBook"),
            eps=info.get("trailingEps"),
            dividend_yield=dividend_yield,
            last_updated=datetime.now().strftime("%Y-%m-%d"),
        )

    def health(self) -> dict:
        """Ping yfinance with a lightweight request."""
        start_ts = time.time()
        try:
            df = yf.Ticker("AAPL").history(period="5d")
            latency_ms = int((time.time() - start_ts) * 1000)
            available = not df.empty
            message = "ok" if available else "empty response"
        except Exception as exc:
            latency_ms = int((time.time() - start_ts) * 1000)
            available = False
            message = str(exc)

        return {
            "available": available,
            "latency_ms": latency_ms,
            "message": message,
        }
