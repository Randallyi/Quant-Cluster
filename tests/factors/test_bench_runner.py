import numpy as np
import pandas as pd
import pytest

from factors.bench_runner import evaluate


def test_perfect_correlation():
    dates = pd.date_range("2024-01-01", periods=100, freq="D")
    factor_values = pd.Series(np.arange(100), index=dates)
    fwd_ret = pd.Series(np.arange(100) * 0.01, index=dates)
    result = evaluate(factor_values, fwd_ret, fwd_days=5)
    assert result["ic"] > 0.9
    assert result["classification"] == "alive"


def test_no_correlation():
    np.random.seed(13)
    dates = pd.date_range("2024-01-01", periods=100, freq="D")
    factor_values = pd.Series(np.random.randn(100), index=dates)
    fwd_ret = pd.Series(np.random.randn(100) * 0.01, index=dates)
    result = evaluate(factor_values, fwd_ret, fwd_days=5)
    assert abs(result["ic"]) < 0.2
    assert result["classification"] == "dead"


def test_reversed():
    dates = pd.date_range("2024-01-01", periods=100, freq="D")
    factor_values = pd.Series(np.arange(100), index=dates)
    fwd_ret = pd.Series(-np.arange(100) * 0.01, index=dates)
    result = evaluate(factor_values, fwd_ret, fwd_days=5)
    assert result["ic"] < -0.9
    assert result["classification"] == "reversed"


def test_ic_series_length():
    dates = pd.date_range("2024-01-01", periods=50, freq="D")
    factor_values = pd.Series(np.random.randn(50), index=dates)
    fwd_ret = pd.Series(np.random.randn(50) * 0.01, index=dates)
    result = evaluate(factor_values, fwd_ret, fwd_days=5)
    assert len(result["ic_series"]) == 50


def test_turnover():
    dates = pd.date_range("2024-01-01", periods=30, freq="D")
    factor_values = pd.Series([1, 2, 3] * 10, index=dates)
    fwd_ret = pd.Series(np.random.randn(30) * 0.01, index=dates)
    result = evaluate(factor_values, fwd_ret, fwd_days=5)
    assert "turnover" in result
    assert result["turnover"] >= 0
