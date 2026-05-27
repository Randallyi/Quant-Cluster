import numpy as np
import pandas as pd
import pytest

from factors.registry import list_factors, compute


class TestListFactors:
    def test_list_factors_has_academic(self):
        factors_list = list_factors()
        names = [f["name"] for f in factors_list]
        assert "academic_carhart_mom" in names
        assert "academic_smb" in names

    def test_list_factors_filter_by_category(self):
        factors_list = list_factors(category="academic")
        assert all(f["category"] == "academic" for f in factors_list)

    def test_list_factors_empty_category(self):
        factors_list = list_factors(category="nonexistent")
        assert factors_list == []


class TestCompute:
    def test_compute_carhart_mom(self):
        dates = pd.date_range("2023-01-01", periods=300, freq="D")
        close = pd.DataFrame({"SPY": 100.0 + np.arange(300) * 0.1}, index=dates)
        result = compute("academic_carhart_mom", {"close": close})
        assert isinstance(result, pd.DataFrame)

    def test_compute_smb(self):
        dates = pd.date_range("2023-01-01", periods=100, freq="D")
        close = pd.DataFrame({"SPY": 100 + np.random.randn(100).cumsum()}, index=dates)
        volume = pd.DataFrame({"SPY": np.random.randint(1e6, 1e7, 100)}, index=dates)
        result = compute("academic_smb", {"close": close, "volume": volume})
        assert isinstance(result, pd.DataFrame)

    def test_compute_unknown_factor(self):
        with pytest.raises(ValueError, match="not found"):
            compute("unknown.factor", {"close": pd.DataFrame()})

    def test_compute_missing_inputs(self):
        with pytest.raises(ValueError, match="Missing required inputs"):
            compute("academic_smb", {"close": pd.DataFrame()})
