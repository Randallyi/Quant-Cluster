import pytest
import numpy as np
from backtest.engines.options_portfolio import (
    bs_price, bs_greeks, historical_volatility,
    iv_smile_adjustment, OptionPosition,
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
