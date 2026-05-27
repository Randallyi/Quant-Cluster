import numpy as np
import pandas as pd
from factors.registry import compute


def test_sector_alpha_degraded_runs_without_sector():
    """Alpha requiring sector should run without sector via degraded global demean."""
    dates = pd.date_range("2023-01-01", periods=100, freq="D")
    close = pd.DataFrame({
        "SPY": 100 + np.cumsum(np.random.randn(100) * 0.5),
        "QQQ": 100 + np.cumsum(np.random.randn(100) * 0.5),
    }, index=dates)
    panel = {"close": close}
    # alpha101_048 requires sector but has degraded fallback — should succeed
    result = compute("alpha101_048", panel)
    assert isinstance(result, pd.DataFrame)
    assert result.shape[0] == 100
