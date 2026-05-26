import pytest
import json
import math
import subprocess
import sys
from pathlib import Path
import pandas as pd
import numpy as np


def test_end_to_end_global_equity(tmp_path):
    """Full pipeline: config -> tool -> engine -> artifacts."""
    run_dir = tmp_path / "03_backtest"
    run_dir.mkdir()

    # Create sample feature matrix (30 days, SPY only)
    dates = pd.date_range("2024-01-01", periods=30, freq="D")
    np.random.seed(42)
    df = pd.DataFrame({
        "open": 100 + np.random.randn(30).cumsum(),
        "high": 101 + np.random.randn(30).cumsum(),
        "low": 99 + np.random.randn(30).cumsum(),
        "close": 100 + np.random.randn(30).cumsum(),
        "volume": np.random.randint(1_000_000, 10_000_000, 30),
    }, index=dates)
    feature_path = tmp_path / "feature_matrix.parquet"
    df.to_parquet(feature_path)

    # Write config
    config = {
        "strategy_name": "test_strategy",
        "asset_class": "global_equity",
        "codes": ["SPY"],
        "start_date": "2024-01-01",
        "end_date": "2024-01-30",
        "initial_cash": 100000,
        "feature_matrix_path": str(feature_path),
        "signals": {"SPY": [1.0] * 30},
        "costs": {"commission_pct": 0.0005, "slippage_pct": 0.0002},
    }
    config_path = tmp_path / "config.json"
    config_path.write_text(json.dumps(config))

    project_root = Path(__file__).resolve().parents[2]

    # Run dry-run
    dry_result = subprocess.run(
        [sys.executable, "tools/backtest_tool.py",
         "--engine", "global_equity",
         "--config", str(config_path),
         "--out-dir", str(run_dir),
         "--dry-run"],
        capture_output=True,
        text=True,
        cwd=project_root,
    )
    assert dry_result.returncode == 0
    dry_out = json.loads(dry_result.stdout)
    assert dry_out["status"] == "ok"

    # Run actual backtest
    result = subprocess.run(
        [sys.executable, "tools/backtest_tool.py",
         "--engine", "global_equity",
         "--config", str(config_path),
         "--out-dir", str(run_dir)],
        capture_output=True,
        text=True,
        cwd=project_root,
    )
    assert result.returncode == 0, f"stderr: {result.stderr}"
    # stdout may contain multiple JSON dumps; parse the first object
    out, _ = json.JSONDecoder().raw_decode(result.stdout.strip())
    assert isinstance(out, dict)
    required_keys = ("total_return", "sharpe", "max_drawdown", "num_trades")
    for key in required_keys:
        assert key in out, f"Missing key: {key}"
    assert isinstance(out["total_return"], (int, float))
    assert not math.isnan(out["total_return"])

    # Verify artifacts
    assert (run_dir / "artifacts" / "equity.csv").exists()
    assert (run_dir / "artifacts" / "trades.csv").exists()
    assert (run_dir / "artifacts" / "ohlcv_SPY.csv").exists()
    assert (run_dir / "artifacts" / "positions.csv").exists()
    assert (run_dir / "artifacts" / "metrics.csv").exists()
    assert (run_dir / "run_card.json").exists()
    assert (run_dir / "run_card.md").exists()

    # Verify trades happened
    trades_df = pd.read_csv(run_dir / "artifacts" / "trades.csv")
    assert len(trades_df) > 0, "Engine should have generated trades"

    # Verify equity curve
    equity_df = pd.read_csv(run_dir / "artifacts" / "equity.csv")
    assert len(equity_df) == 30, "Equity curve should have 30 rows"
    assert equity_df["equity"].iloc[0] > 0
    assert equity_df["equity"].iloc[-1] > 0

    # Verify positions
    positions_df = pd.read_csv(run_dir / "artifacts" / "positions.csv")
    assert len(positions_df) == 30

    # Verify run_card content
    run_card = json.loads((run_dir / "run_card.json").read_text())
    assert run_card["schema_version"] == "0.1"
    assert "metrics" in run_card
