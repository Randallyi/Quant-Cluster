import pytest
import pandas as pd
import numpy as np
from unittest.mock import patch, MagicMock
from backtest.engines.benchmark import resolve_benchmark, _build_result


def test_resolve_benchmark_prefers_ibkr():
    """IBKR success should be used, yfinance not called."""
    mock_ibkr_df = pd.DataFrame({
        "open": [100], "high": [101], "low": [99], "close": [100], "volume": [1000]
    }, index=pd.to_datetime(["2024-01-01"]))
    
    with patch("backtest.engines.benchmark._fetch_from_ibkr", return_value=mock_ibkr_df) as mock_ibkr:
        with patch("backtest.engines.benchmark._fetch_from_yfinance") as mock_yf:
            result = resolve_benchmark("SPY", data_router_url="http://test:8080")
            
            assert result is not None
            assert result.source == "ibkr"
            mock_ibkr.assert_called_once()
            mock_yf.assert_not_called()


def test_resolve_benchmark_falls_back_to_yfinance():
    """IBKR empty → yfinance used."""
    mock_yf_df = pd.DataFrame({
        "open": [100], "high": [101], "low": [99], "close": [100], "volume": [1000]
    }, index=pd.to_datetime(["2024-01-01"]))
    
    with patch("backtest.engines.benchmark._fetch_from_ibkr", return_value=pd.DataFrame()):
        with patch("backtest.engines.benchmark._fetch_from_yfinance", return_value=mock_yf_df):
            result = resolve_benchmark("SPY", data_router_url="http://test:8080")
            
            assert result is not None
            assert result.source == "yfinance"


def test_resolve_benchmark_returns_none_when_all_fail():
    """All sources fail → None."""
    with patch("backtest.engines.benchmark._fetch_from_ibkr", return_value=pd.DataFrame()):
        with patch("backtest.engines.benchmark._fetch_from_yfinance", return_value=pd.DataFrame()):
            result = resolve_benchmark("SPY", data_router_url="http://test:8080")
            assert result is None


def test_build_result():
    df = pd.DataFrame({
        "close": [100, 101, 102],
    }, index=pd.to_datetime(["2024-01-01", "2024-01-02", "2024-01-03"]))
    result = _build_result("SPY", df, "ibkr")
    assert result.ticker == "SPY"
    assert result.source == "ibkr"
    assert result.total_ret > 0
