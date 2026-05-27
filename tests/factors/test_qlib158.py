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
        else:
            raise ValueError(f"Unknown field: {field}")
    return panel


class TestQlib158:
    def test_beta10(self):
        """close-only, safe_div + delta."""
        panel = _make_panel(["close"])
        result = compute("qlib158_beta10", panel)
        assert isinstance(result, pd.DataFrame)
        assert result.shape[0] == 300

    def test_cntp5(self):
        """close-only, rolling mean of up-days."""
        panel = _make_panel(["close"])
        result = compute("qlib158_cntp5", panel)
        assert isinstance(result, pd.DataFrame)

    def test_corr10(self):
        """close + volume, ts_corr."""
        panel = _make_panel(["close", "volume"])
        result = compute("qlib158_corr10", panel)
        assert isinstance(result, pd.DataFrame)

    def test_vstd5(self):
        """volume-only."""
        panel = _make_panel(["volume"])
        result = compute("qlib158_vstd5", panel)
        assert isinstance(result, pd.DataFrame)

    def test_klen(self):
        """full OHLCV — K-line length proxy."""
        panel = _make_panel(["open", "high", "low", "close"])
        result = compute("qlib158_klen", panel)
        assert isinstance(result, pd.DataFrame)

    def test_imax5(self):
        """high-only — intraday max position."""
        panel = _make_panel(["high"])
        result = compute("qlib158_imax5", panel)
        assert isinstance(result, pd.DataFrame)

    def test_imin10(self):
        """low-only — intraday min position."""
        panel = _make_panel(["low"])
        result = compute("qlib158_imin10", panel)
        assert isinstance(result, pd.DataFrame)
