import pytest
import pandas as pd
import numpy as np
from backtest.engines.base import BaseEngine


class DummyEngine(BaseEngine):
    """Concrete engine for testing."""
    def can_execute(self, symbol, direction, bar):
        return True
    def round_size(self, raw_size, price):
        return round(raw_size, 2)
    def calc_commission(self, size, price, direction, is_open):
        return size * price * 0.001
    def apply_slippage(self, price, direction):
        return price * (1 + direction * 0.0005)


def test_dummy_engine_runs(sample_data_map, sample_signal_map, tmp_run_dir):
    config = {"initial_cash": 100000, "leverage": 1.0}
    engine = DummyEngine(config)

    metrics = engine.run_backtest(
        config=config,
        data_map=sample_data_map,
        signal_map=sample_signal_map,
        run_dir=tmp_run_dir,
        bars_per_year=252,
    )

    assert "sharpe" in metrics
    assert metrics["num_trades"] >= 0
    assert (tmp_run_dir / "artifacts" / "equity.csv").exists()
    assert (tmp_run_dir / "artifacts" / "trades.csv").exists()
