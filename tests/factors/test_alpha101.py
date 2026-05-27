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


class TestAlpha101:
    def test_alpha001(self):
        panel = _make_panel(["close"])
        result = compute("alpha101_001", panel)
        assert isinstance(result, pd.DataFrame)
        assert result.shape[0] == 300

    def test_alpha002(self):
        panel = _make_panel(["open", "close", "volume"])
        result = compute("alpha101_002", panel)
        assert isinstance(result, pd.DataFrame)

    def test_alpha003(self):
        panel = _make_panel(["open", "volume", "close"])
        result = compute("alpha101_003", panel)
        assert isinstance(result, pd.DataFrame)

    def test_alpha010(self):
        panel = _make_panel(["close", "volume", "vwap"])
        result = compute("alpha101_010", panel)
        assert isinstance(result, pd.DataFrame)

    def test_alpha050(self):
        panel = _make_panel(["volume", "vwap", "close"])
        result = compute("alpha101_050", panel)
        assert isinstance(result, pd.DataFrame)

    def test_alpha101(self):
        panel = _make_panel(["open", "high", "low", "close"])
        result = compute("alpha101_101", panel)
        assert isinstance(result, pd.DataFrame)
