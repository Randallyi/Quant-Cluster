import numpy as np
import pandas as pd
import pytest

from factors.zoo.academic import carhart_mom, smb, hml, rmw, cma, mkt_rf


def test_carhart_mom_compute():
    dates = pd.date_range("2023-01-01", periods=300, freq="D")
    close = pd.DataFrame({"SPY": 100 + np.arange(300) * 0.1}, index=dates)
    panel = {"close": close}
    result = carhart_mom.compute(panel)
    assert isinstance(result, pd.DataFrame)
    assert result.shape[0] == 300


def test_carhart_mom_meta():
    assert carhart_mom.__alpha_meta__["id"] == "academic_carhart_mom"
    assert "close" in carhart_mom.__alpha_meta__["columns_required"]


def test_smb_compute():
    dates = pd.date_range("2023-01-01", periods=100, freq="D")
    close = pd.DataFrame({"SPY": 100 + np.random.randn(100).cumsum()}, index=dates)
    volume = pd.DataFrame({"SPY": np.random.randint(1e6, 1e7, 100)}, index=dates)
    panel = {"close": close, "volume": volume}
    result = smb.compute(panel)
    assert isinstance(result, pd.DataFrame)


def test_mkt_rf_compute():
    dates = pd.date_range("2023-01-01", periods=100, freq="D")
    close = pd.DataFrame({"SPY": 100 + np.random.randn(100).cumsum()}, index=dates)
    panel = {"close": close}
    result = mkt_rf.compute(panel)
    assert isinstance(result, pd.DataFrame)
