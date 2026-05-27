import numpy as np
import pandas as pd
from factors.registry import _derive_fields


def test_amount_auto_derived():
    """amount should be auto-derived from close * volume when absent."""
    dates = pd.date_range("2023-01-01", periods=100, freq="D")
    close = pd.DataFrame({"SPY": 100 + np.cumsum(np.random.randn(100) * 0.5)}, index=dates)
    volume = pd.DataFrame({"SPY": np.random.randint(1_000_000, 10_000_000, 100)}, index=dates)
    panel = {"close": close, "volume": volume}

    derived = _derive_fields(panel)
    assert "amount" in derived
    pd.testing.assert_frame_equal(derived["amount"], close * volume)


def test_amount_not_overwritten():
    """If amount is already present, _derive_fields should not overwrite it."""
    dates = pd.date_range("2023-01-01", periods=5, freq="D")
    close = pd.DataFrame({"SPY": [100.0, 101.0, 102.0, 103.0, 104.0]}, index=dates)
    volume = pd.DataFrame({"SPY": [1000.0, 2000.0, 3000.0, 4000.0, 5000.0]}, index=dates)
    existing_amount = pd.DataFrame({"SPY": [999.0, 999.0, 999.0, 999.0, 999.0]}, index=dates)
    panel = {"close": close, "volume": volume, "amount": existing_amount}

    derived = _derive_fields(panel)
    pd.testing.assert_frame_equal(derived["amount"], existing_amount)


def test_amount_not_derived_without_close():
    """If close is missing, amount should not be derived."""
    dates = pd.date_range("2023-01-01", periods=5, freq="D")
    volume = pd.DataFrame({"SPY": [1000.0, 2000.0, 3000.0, 4000.0, 5000.0]}, index=dates)
    panel = {"volume": volume}

    derived = _derive_fields(panel)
    assert "amount" not in derived
