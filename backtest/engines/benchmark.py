"""Benchmark ticker resolution and fetch for backtest comparison.

Provides a lightweight, zero-dependency way to fetch benchmark reference
data given a set of strategy codes and a data source.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Optional

import pandas as pd

# -------------------------------------------------------------------
# Benchmark map: market type → default ticker
# -------------------------------------------------------------------

MARKET_BENCHMARKS: dict[str, Optional[str]] = {
    "us_equity": "SPY",
    "hk_equity": "HK.03100",  # Hang Seng China Enterprises ETF
    "a_share": "000300.SH",  # CSI 300 (China A-share core index)
    "crypto": "BTC-USDT",
    "futures": "ES.CME",  # E-mini S&P 500 futures
    "forex": None,  # no universal benchmark
}


@dataclass
class BenchmarkResult:
    ticker: str
    ret_series: pd.Series  # per-bar returns, index = timestamps
    total_ret: float  # total return over the period


def resolve_benchmark(
    strategy_codes: list[str],
    data_source_path: str,
    explicit: Optional[str] = None,
) -> Optional[BenchmarkResult]:
    """Resolve the appropriate benchmark ticker and fetch its return series.

    Args:
        strategy_codes: Instruments being backtested (used for market inference).
        data_source_path: Path to directory containing benchmark data files.
        explicit: Override ticker (e.g. "SPY" passed via config).

    Returns:
        BenchmarkResult with return series and total return, or None if no
        benchmark applies (forex, or fetch failure).
    """
    ticker = _resolve_ticker(strategy_codes, explicit)
    if ticker is None:
        return None

    try:
        bench_df = _fetch_benchmark(ticker, data_source_path)
    except Exception:
        return None

    if bench_df.empty or "close" not in bench_df.columns:
        return None

    close = bench_df["close"].dropna()
    if len(close) < 2:
        return None

    ret_series = close.pct_change().fillna(0.0)
    total_ret = float((1 + ret_series).prod() - 1)

    return BenchmarkResult(ticker=ticker, ret_series=ret_series, total_ret=total_ret)


# -------------------------------------------------------------------
# Internal helpers
# -------------------------------------------------------------------


def _resolve_ticker(
    codes: list[str],
    explicit: Optional[str],
) -> Optional[str]:
    """Pick the benchmark ticker to use."""

    if explicit:
        return explicit

    # Infer market from source + first code pattern
    market = _infer_market(codes)
    ticker = MARKET_BENCHMARKS.get(market)

    return ticker


def _infer_market(codes: list[str]) -> str:
    """Rough market inference from symbol patterns and source."""
    if not codes:
        return "us_equity"

    first = codes[0].upper()

    if "-" in first or "/" in first:
        return "crypto"
    if first.endswith(".US"):
        return "us_equity"
    if first.endswith(".HK"):
        return "hk_equity"
    if first.isdigit() and len(first) == 6:
        return "a_share"
    if first.startswith(("IF", "IC", "IH", "IM", "T", "TF")):
        return "futures"

    return "us_equity"


def _fetch_benchmark(ticker: str, data_source_path: str) -> pd.DataFrame:
    """Fetch benchmark data from local file.

    Args:
        ticker: Benchmark ticker (e.g., "SPY").
        data_source_path: Path to directory containing benchmark data files.

    Returns:
        DataFrame with OHLCV data, or empty DataFrame if not found.
    """
    source_dir = Path(data_source_path)
    for ext in [".parquet", ".csv"]:
        path = source_dir / f"{ticker}{ext}"
        if path.exists():
            if ext == ".parquet":
                return pd.read_parquet(path)
            else:
                df = pd.read_csv(path, index_col=0, parse_dates=True)
                return df
    return pd.DataFrame()
