import numpy as np
import pandas as pd
import pytest

from factors.registry import compute


def _make_panel(fields):
    """Helper: create synthetic OHLCV+ panel."""
    dates = pd.date_range("2023-01-01", periods=300, freq="D")
    symbols = ["SPY", "QQQ"]
    np.random.seed(42)
    panel = {}
    for field in fields:
        if field in ("open", "high", "low", "close"):
            panel[field] = pd.DataFrame(
                {sym: 100 + np.cumsum(np.random.randn(300) * 0.5) + np.random.randn(300) * 0.1
                 for sym in symbols},
                index=dates
            )
        elif field == "volume":
            panel[field] = pd.DataFrame(
                {sym: np.random.randint(1_000_000, 10_000_000, 300) for sym in symbols},
                index=dates
            )
        elif field == "vwap":
            panel[field] = pd.DataFrame(
                {sym: 100 + np.cumsum(np.random.randn(300) * 0.3) for sym in symbols},
                index=dates
            )
        else:
            raise ValueError(f"Unknown field: {field}")
    return panel


class TestGtja191:
    def test_gtja001(self):
        panel = _make_panel(["volume", "close", "open"])
        result = compute("gtja191_001", panel)
        assert isinstance(result, pd.DataFrame)
        assert result.shape[0] == 300

    def test_gtja050(self):
        panel = _make_panel(["high", "low"])
        result = compute("gtja191_050", panel)
        assert isinstance(result, pd.DataFrame)

    def test_gtja007_amount_derived(self):
        """Alpha needing amount — should work via auto-derivation (close * volume)."""
        panel = _make_panel(["close", "volume"])
        result = compute("gtja191_007", panel)
        assert isinstance(result, pd.DataFrame)

    def test_gtja012_amount_derived(self):
        """Alpha needing amount + open — should work via auto-derivation."""
        panel = _make_panel(["open", "close", "volume"])
        result = compute("gtja191_012", panel)
        assert isinstance(result, pd.DataFrame)

    def test_gtja090_amount_derived(self):
        """Alpha needing volume + amount — should work via auto-derivation (close * volume)."""
        panel = _make_panel(["close", "volume"])
        result = compute("gtja191_090", panel)
        assert isinstance(result, pd.DataFrame)

    def test_gtja191(self):
        panel = _make_panel(["open", "high", "low", "close", "volume"])
        result = compute("gtja191_191", panel)
        assert isinstance(result, pd.DataFrame)
