import pytest
import pandas as pd
import numpy as np
from pathlib import Path


@pytest.fixture
def sample_data_map():
    dates = pd.date_range("2024-01-01", periods=30, freq="D")
    np.random.seed(42)
    spy = pd.DataFrame({
        "open": 100 + np.random.randn(30).cumsum(),
        "high": 101 + np.random.randn(30).cumsum(),
        "low": 99 + np.random.randn(30).cumsum(),
        "close": 100 + np.random.randn(30).cumsum(),
        "volume": np.random.randint(1_000_000, 10_000_000, 30),
    }, index=dates)
    tlt = pd.DataFrame({
        "open": 90 + np.random.randn(30).cumsum(),
        "high": 91 + np.random.randn(30).cumsum(),
        "low": 89 + np.random.randn(30).cumsum(),
        "close": 90 + np.random.randn(30).cumsum(),
        "volume": np.random.randint(500_000, 5_000_000, 30),
    }, index=dates)
    return {"SPY": spy, "TLT": tlt}


@pytest.fixture
def sample_signal_map(sample_data_map):
    signals = {}
    for code, df in sample_data_map.items():
        signals[code] = pd.Series(1.0 if code == "SPY" else 0.0, index=df.index)
    return signals


@pytest.fixture
def tmp_run_dir(tmp_path):
    run_dir = tmp_path / "03_backtest"
    run_dir.mkdir(parents=True, exist_ok=True)
    return run_dir
