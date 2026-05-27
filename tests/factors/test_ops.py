import numpy as np
import pandas as pd
import pytest

from factors.core.ops import (
    rank,
    scale,
    ts_rank,
    ts_corr,
    ts_cov,
    ts_mean,
    ts_std,
    ts_max,
    ts_min,
    ts_argmax,
    ts_argmin,
    delta,
    decay_linear,
    signed_power,
    safe_div,
    vwap,
)


def test_rank_basic():
    df = pd.DataFrame({"A": [1.0, 3.0], "B": [3.0, 1.0]})
    result = rank(df)
    # Row 0: A is min (rank 1/2 = 0.5), B is max (rank 2/2 = 1.0)
    assert result.iloc[0, 0] == pytest.approx(0.5)
    assert result.iloc[0, 1] == pytest.approx(1.0)


def test_scale_basic():
    df = pd.DataFrame({"A": [1.0, -1.0], "B": [1.0, -1.0]})
    result = scale(df)
    assert result.iloc[0, 0] == pytest.approx(0.5)


def test_ts_rank_basic():
    df = pd.DataFrame({"A": [1.0, 2.0, 3.0, 4.0]})
    result = ts_rank(df, 3)
    assert result.iloc[2, 0] == pytest.approx(1.0)


def test_ts_corr_perfect():
    x = pd.DataFrame({"A": [1.0, 2.0, 3.0, 4.0, 5.0]})
    y = pd.DataFrame({"A": [1.0, 2.0, 3.0, 4.0, 5.0]})
    result = ts_corr(x, y, 3)
    assert result.iloc[4, 0] == pytest.approx(1.0)


def test_ts_cov_basic():
    x = pd.DataFrame({"A": [1.0, 2.0, 3.0, 4.0, 5.0]})
    y = pd.DataFrame({"A": [1.0, 2.0, 3.0, 4.0, 5.0]})
    result = ts_cov(x, y, 3)
    assert result.iloc[4, 0] > 0


def test_ts_mean_basic():
    df = pd.DataFrame({"A": [1.0, 2.0, 3.0]})
    result = ts_mean(df, 2)
    assert result.iloc[1, 0] == pytest.approx(1.5)


def test_ts_std_basic():
    df = pd.DataFrame({"A": [1.0, 3.0]})
    result = ts_std(df, 2)
    assert result.iloc[1, 0] == pytest.approx(np.sqrt(2.0))


def test_ts_max_basic():
    df = pd.DataFrame({"A": [1.0, 3.0, 2.0]})
    result = ts_max(df, 2)
    assert result.iloc[1, 0] == pytest.approx(3.0)


def test_ts_min_basic():
    df = pd.DataFrame({"A": [3.0, 1.0, 2.0]})
    result = ts_min(df, 2)
    assert result.iloc[1, 0] == pytest.approx(1.0)


def test_ts_argmax_basic():
    df = pd.DataFrame({"A": [1.0, 3.0, 2.0]})
    result = ts_argmax(df, 3)
    assert result.iloc[2, 0] == pytest.approx(1.0)


def test_ts_argmin_basic():
    df = pd.DataFrame({"A": [3.0, 1.0, 2.0]})
    result = ts_argmin(df, 3)
    assert result.iloc[2, 0] == pytest.approx(1.0)


def test_delta_basic():
    df = pd.DataFrame({"A": [1.0, 3.0, 6.0]})
    result = delta(df, 1)
    assert result.iloc[1, 0] == pytest.approx(2.0)
    assert result.iloc[2, 0] == pytest.approx(3.0)


def test_decay_linear_basic():
    df = pd.DataFrame({"A": [1.0, 2.0, 3.0]})
    result = decay_linear(df, 2)
    # weights [2/3, 1/3], dot([1,2]) = 4/3, dot([2,3]) = 7/3
    assert result.iloc[1, 0] == pytest.approx(4.0 / 3.0)


def test_signed_power_basic():
    df = pd.DataFrame({"A": [-2.0, 3.0]})
    result = signed_power(df, 2.0)
    assert result.iloc[0, 0] == pytest.approx(-4.0)
    assert result.iloc[1, 0] == pytest.approx(9.0)


def test_safe_div_basic():
    a = pd.DataFrame({"A": [1.0, 2.0]})
    b = pd.DataFrame({"A": [2.0, 0.0]})
    result = safe_div(a, b)
    assert result.iloc[0, 0] == pytest.approx(0.5)
    assert np.isnan(result.iloc[1, 0])


def test_vwap_basic():
    panel = {
        "open": pd.DataFrame({"SPY": [10.0, 11.0]}),
        "high": pd.DataFrame({"SPY": [12.0, 13.0]}),
        "low": pd.DataFrame({"SPY": [9.0, 10.0]}),
        "close": pd.DataFrame({"SPY": [11.0, 12.0]}),
    }
    result = vwap(panel)
    assert result.iloc[0, 0] == pytest.approx((10 + 12 + 9 + 11) / 4)
