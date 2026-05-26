import pytest
import pandas as pd
import numpy as np
from backtest.engines.benchmark import resolve_benchmark, _infer_market


def test_infer_market():
    assert _infer_market(["SPY"]) == "us_equity"
    assert _infer_market(["000300.SH"]) == "us_equity"
    assert _infer_market(["BTC-USDT"]) == "crypto"


def test_resolve_benchmark_with_dummy_file(tmp_path):
    # Create dummy SPY data
    dates = pd.date_range("2024-01-01", periods=10, freq="D")
    df = pd.DataFrame({
        "close": 100 + np.random.randn(10).cumsum(),
    }, index=dates)
    df.to_csv(tmp_path / "SPY.csv")

    result = resolve_benchmark(
        strategy_codes=["SPY"],
        data_source_path=str(tmp_path),
        explicit="SPY",
    )

    assert result is not None
    assert result.ticker == "SPY"
    assert len(result.ret_series) == 10


def test_resolve_benchmark_not_found(tmp_path):
    result = resolve_benchmark(
        strategy_codes=["SPY"],
        data_source_path=str(tmp_path),
        explicit="NONEXISTENT",
    )
    assert result is None
