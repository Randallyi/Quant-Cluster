import pytest
import pandas as pd
from backtest.engines.global_equity import GlobalEquityEngine


def test_us_market_rules():
    config = {"initial_cash": 100000, "leverage": 1.0, "slippage_us": 0.0005}
    engine = GlobalEquityEngine(config, market="us")

    # can_execute: US allows both directions
    assert engine.can_execute("SPY", 1, pd.Series()) is True
    assert engine.can_execute("SPY", -1, pd.Series()) is True

    # round_size: US supports fractional shares
    assert engine.round_size(10.567, 100.0) == 10.57

    # commission: US zero commission
    assert engine.calc_commission(100, 100.0, 1, True) == 0.0

    # slippage
    slipped = engine.apply_slippage(100.0, 1)
    assert slipped == 100.0 * (1 + 0.0005)


def test_hk_market_rules():
    config = {"initial_cash": 100000, "leverage": 1.0}
    engine = GlobalEquityEngine(config, market="hk")

    # round_size: HK 100-share lots
    assert engine.round_size(150, 50.0) == 100
    assert engine.round_size(250, 50.0) == 200

    # commission: HK has stamp tax + levies
    comm = engine.calc_commission(100, 50.0, 1, True)
    assert comm > 0.0
