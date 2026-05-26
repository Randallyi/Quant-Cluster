import pytest
import numpy as np
import pandas as pd
from pathlib import Path
from backtest.engines.options_portfolio import (
    bs_price, bs_greeks, historical_volatility,
    iv_smile_adjustment, OptionPosition, run_options_backtest,
)


def test_bs_price_call():
    price = bs_price(S=100, K=100, T=1.0, r=0.05, sigma=0.2, option_type="call")
    assert 10.0 < price < 11.0  # ≈ 10.45


def test_bs_price_put():
    price = bs_price(S=100, K=100, T=1.0, r=0.05, sigma=0.2, option_type="put")
    assert 5.0 < price < 6.0


def test_bs_greeks_call():
    greeks = bs_greeks(S=100, K=100, T=1.0, r=0.05, sigma=0.2, option_type="call")
    assert 0.5 < greeks["delta"] < 0.7
    assert greeks["gamma"] > 0
    assert greeks["theta"] < 0
    assert greeks["vega"] > 0


def test_iv_smile_adjustment():
    iv = iv_smile_adjustment(S=100, K=110, base_iv=0.2, skew=-0.15, curvature=0.05)
    assert iv != 0.2  # should be adjusted for moneyness
    assert iv >= 0.01


def test_option_position_intrinsic():
    pos = OptionPosition("call", 100, "2024-12-31", 1, 10.0, "2024-01-01", "SPY")
    assert pos.intrinsic_value(110) == 10.0
    assert pos.intrinsic_value(90) == 0.0


def test_run_options_backtest_long_call_itm():
    """Long call that expires ITM."""
    dates = pd.date_range("2024-01-01", periods=30, freq="D")
    # Underlying rises from 100 to 110
    spy = pd.DataFrame({
        "open": np.linspace(100, 110, 30),
        "high": np.linspace(101, 111, 30),
        "low": np.linspace(99, 109, 30),
        "close": np.linspace(100, 110, 30),
        "volume": np.ones(30) * 1e6,
    }, index=dates)
    data_map = {"SPY": spy}
    
    # Signal: open long call at strike 100, expiry 2024-02-01
    signals = [{
        "date": "2024-01-02",
        "action": "open",
        "underlying": "SPY",
        "legs": [{"type": "call", "strike": 100.0, "expiry": "2024-02-01", "qty": 1}],
    }]
    
    config = {
        "codes": ["SPY"],
        "start_date": "2024-01-01",
        "end_date": "2024-01-30",
        "initial_cash": 100000,
        "commission": 0.001,
        "options_config": {"risk_free_rate": 0.05, "contract_multiplier": 1.0},
    }
    
    import tempfile
    with tempfile.TemporaryDirectory() as tmp:
        run_dir = Path(tmp)
        metrics = run_options_backtest(config, data_map, signals, run_dir)
        
        assert metrics["trade_count"] > 0
        assert metrics["final_value"] > 0
        assert (run_dir / "artifacts" / "equity.csv").exists()


def test_run_options_backtest_empty_signals():
    """Empty signal map should return metrics with no trades."""
    dates = pd.date_range("2024-01-01", periods=10, freq="D")
    spy = pd.DataFrame({
        "open": [100] * 10, "high": [101] * 10, "low": [99] * 10,
        "close": [100] * 10, "volume": [1e6] * 10,
    }, index=dates)
    
    config = {
        "codes": ["SPY"], "start_date": "2024-01-01", "end_date": "2024-01-10",
        "initial_cash": 100000, "commission": 0.001,
        "options_config": {},
    }
    
    import tempfile
    with tempfile.TemporaryDirectory() as tmp:
        run_dir = Path(tmp)
        metrics = run_options_backtest(config, {"SPY": spy}, [], run_dir)
        
        assert metrics["trade_count"] == 0
        assert metrics["final_value"] == 100000


def test_run_options_backtest_multi_leg_spread():
    """Bull call spread: long lower strike, short higher strike."""
    dates = pd.date_range("2024-01-01", periods=20, freq="D")
    spy = pd.DataFrame({
        "open": np.linspace(100, 105, 20),
        "high": np.linspace(101, 106, 20),
        "low": np.linspace(99, 104, 20),
        "close": np.linspace(100, 105, 20),
        "volume": np.ones(20) * 1e6,
    }, index=dates)
    
    signals = [{
        "date": "2024-01-02",
        "action": "open",
        "underlying": "SPY",
        "legs": [
            {"type": "call", "strike": 100.0, "expiry": "2024-02-01", "qty": 1},
            {"type": "call", "strike": 105.0, "expiry": "2024-02-01", "qty": -1},
        ],
    }]
    
    config = {
        "codes": ["SPY"], "start_date": "2024-01-01", "end_date": "2024-01-20",
        "initial_cash": 100000, "commission": 0.001,
        "options_config": {},
    }
    
    import tempfile
    with tempfile.TemporaryDirectory() as tmp:
        run_dir = Path(tmp)
        metrics = run_options_backtest(config, {"SPY": spy}, signals, run_dir)
        
        assert metrics["trade_count"] > 0
