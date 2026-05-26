import pytest
import pandas as pd
import numpy as np
from backtest.engines.validation import monte_carlo_test, bootstrap_sharpe_ci, walk_forward_analysis


class FakeTrade:
    def __init__(self, pnl, entry_time=None):
        self.pnl = pnl
        self.entry_time = entry_time if entry_time is not None else 0


def test_monte_carlo_with_profitable_trades():
    trades = [FakeTrade(1000), FakeTrade(-200), FakeTrade(500), FakeTrade(300)]
    result = monte_carlo_test(trades, initial_capital=100000, n_simulations=100, seed=42)
    assert "p_value_sharpe" in result
    assert 0.0 <= result["p_value_sharpe"] <= 1.0
    assert result["n_trades"] == 4


def test_bootstrap_sharpe_ci():
    np.random.seed(42)
    equity = pd.Series(100000 * (1 + np.random.randn(100) * 0.01).cumprod())
    result = bootstrap_sharpe_ci(equity, n_bootstrap=100, seed=42)
    assert "ci_lower" in result
    assert "ci_upper" in result
    assert result["ci_lower"] < result["ci_upper"]


def test_walk_forward_analysis():
    np.random.seed(42)
    equity = pd.Series(100000 * (1 + np.random.randn(50) * 0.01).cumprod())
    trades = [FakeTrade(100, entry_time=5), FakeTrade(-50, entry_time=20)]
    result = walk_forward_analysis(equity, trades, n_windows=3, bars_per_year=252)
    assert result["n_windows"] == 3
    assert len(result["windows"]) == 3
