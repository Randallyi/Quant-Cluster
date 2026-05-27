"""Benchmark ticker resolution and fetch for backtest comparison.

Fetches benchmark data through data_router HTTP API with fallback chain:
  1. IBKR (preferred — data_engineer likely already cached it)
  2. yfinance (fallback)
  3. Local file (final fallback)
"""

from __future__ import annotations

import logging
import os
from dataclasses import dataclass
from pathlib import Path
from typing import Optional

import pandas as pd
import requests

logger = logging.getLogger(__name__)


DATA_ROUTER_URL = os.getenv("DATA_ROUTER_URL", "http://data_router:8080")


@dataclass
class BenchmarkResult:
    ticker: str
    ret_series: pd.Series       # per-bar returns, index = timestamps
    total_ret: float            # total return over the period
    source: str                 # "ibkr" | "yfinance" | "local" | ""


# -------------------------------------------------------------------
# Public API
# -------------------------------------------------------------------


def resolve_benchmark(
    ticker: str,
    data_router_url: str = "",
    data_source_path: str = "",
    start_date: str = "",
    end_date: str = "",
) -> Optional[BenchmarkResult]:
    """Resolve benchmark with IBKR → yfinance → local file fallback chain.

    Args:
        ticker: Benchmark ticker (e.g., "SPY").
        data_router_url: data_router base URL. Defaults to DATA_ROUTER_URL env var.
        data_source_path: Optional local directory for file fallback.
        start_date: Start date (YYYY-MM-DD).
        end_date: End date (YYYY-MM-DD).

    Returns:
        BenchmarkResult with return series and source tag, or None if unavailable.
    """
    url = data_router_url or DATA_ROUTER_URL

    # Layer 1: IBKR (preferred — likely cached by data_engineer)
    df = _fetch_from_ibkr(ticker, url, start_date, end_date)
    if not df.empty:
        return _build_result(ticker, df, "ibkr")

    # Layer 2: yfinance fallback
    df = _fetch_from_yfinance(ticker, url, start_date, end_date)
    if not df.empty:
        return _build_result(ticker, df, "yfinance")

    # Layer 3: local file fallback
    if data_source_path:
        df = _fetch_from_local(ticker, data_source_path)
        if not df.empty:
            return _build_result(ticker, df, "local")

    return None


# -------------------------------------------------------------------
# Internal fetchers
# -------------------------------------------------------------------


def _fetch_from_ibkr(ticker: str, base_url: str, start_date: str, end_date: str) -> pd.DataFrame:
    """Fetch benchmark via data_router IBKR endpoint."""
    try:
        # Format endDateTime as YYYYMMDD-HH:MM:SS (TWS/IBKR expects this)
        formatted_end = ""
        if end_date:
            formatted_end = f"{end_date.replace('-', '')}-23:59:59"

        # Compute durationStr dynamically
        duration = "1 Y"  # default
        if start_date and end_date:
            try:
                start_dt = pd.Timestamp(start_date)
                end_dt = pd.Timestamp(end_date)
                days = (end_dt - start_dt).days
                if days <= 0:
                    duration = "1 D"
                elif days <= 30:
                    duration = f"{days} D"
                elif days <= 180:
                    duration = f"{days // 30} M"
                else:
                    duration = f"{max(1, days // 365)} Y"
            except Exception:
                pass  # fallback to default

        req = {
            "contract": {
                "symbol": ticker,
                "secType": "ETF" if ticker in ("SPY", "TLT", "QQQ", "IWM") else "STK",
                "exchange": "SMART",
                "currency": "USD",
            },
            "endDateTime": formatted_end,
            "durationStr": duration,
            "barSizeSetting": "1 day",
            "whatToShow": "TRADES",
            "useRTH": True,
        }
        resp = requests.post(
            f"{base_url}/data/ibkr/historical",
            json=req,
            timeout=30,
        )
        resp.raise_for_status()
        payload = resp.json()

        if payload.get("status") != "success":
            return pd.DataFrame()

        bars = payload.get("data", [])
        if not bars:
            return pd.DataFrame()

        df = pd.DataFrame(bars)
        df["date"] = pd.to_datetime(df["date"])
        df = df.set_index("date").sort_index()
        return df[["open", "high", "low", "close", "volume"]]

    except Exception as exc:
        logger.warning("IBKR fetch failed for %s: %s", ticker, exc)
        return pd.DataFrame()


def _fetch_from_yfinance(ticker: str, base_url: str, start_date: str, end_date: str) -> pd.DataFrame:
    """Fetch benchmark via data_router yfinance endpoint."""
    try:
        req = {
            "ticker": ticker,
            "start": start_date,
            "end": end_date,
            "interval": "1d",
            "auto_adjust": True,
        }
        resp = requests.post(
            f"{base_url}/data/yfinance/historical",
            json=req,
            timeout=30,
        )
        resp.raise_for_status()
        payload = resp.json()

        if payload.get("status") != "success":
            return pd.DataFrame()

        bars = payload.get("data", [])
        if not bars:
            return pd.DataFrame()

        df = pd.DataFrame(bars)
        df["date"] = pd.to_datetime(df["date"])
        df = df.set_index("date").sort_index()
        return df[["open", "high", "low", "close", "volume"]]

    except Exception as exc:
        logger.warning("yfinance fetch failed for %s: %s", ticker, exc)
        return pd.DataFrame()


def _fetch_from_local(ticker: str, data_source_path: str) -> pd.DataFrame:
    """Fetch benchmark from local parquet or CSV file."""
    try:
        source_dir = Path(data_source_path)
        for ext in [".parquet", ".csv"]:
            path = source_dir / f"{ticker}{ext}"
            if path.exists():
                if ext == ".parquet":
                    df = pd.read_parquet(path)
                else:
                    df = pd.read_csv(path, index_col=0, parse_dates=True)
                if "close" in df.columns:
                    return df
    except Exception as exc:
        logger.warning("Local file fetch failed for %s: %s", ticker, exc)
    return pd.DataFrame()


def _build_result(ticker: str, df: pd.DataFrame, source: str) -> BenchmarkResult:
    """Build BenchmarkResult from OHLCV DataFrame."""
    close = df["close"].dropna()
    ret_series = close.pct_change().fillna(0.0)
    total_ret = float((1 + ret_series).prod() - 1)
    return BenchmarkResult(
        ticker=ticker,
        ret_series=ret_series,
        total_ret=total_ret,
        source=source,
    )
