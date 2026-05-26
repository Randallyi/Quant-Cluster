import subprocess
import sys
import json
import tempfile
from pathlib import Path

import pandas as pd


def test_backtest_tool_schema():
    result = subprocess.run(
        [sys.executable, "tools/backtest_tool.py", "--engine", "global_equity", "--schema"],
        capture_output=True,
        text=True,
        cwd=Path(__file__).resolve().parents[2],
    )
    assert result.returncode == 0
    schema = json.loads(result.stdout)
    assert schema["engine"] == "global_equity"


def test_backtest_tool_dry_run_missing_config():
    result = subprocess.run(
        [sys.executable, "tools/backtest_tool.py", "--engine", "global_equity", "--config", "/nonexistent.json", "--dry-run"],
        capture_output=True,
        text=True,
        cwd=Path(__file__).resolve().parents[2],
    )
    assert result.returncode != 0
    err = json.loads(result.stderr)
    assert err["error_type"] == "DATA_NOT_FOUND"


def test_backtest_tool_dry_run_success():
    """Dry-run with valid config should succeed."""
    with tempfile.TemporaryDirectory() as tmp:
        tmp_path = Path(tmp)
        # Create dummy feature matrix
        df = pd.DataFrame({
            "open": [100.0], "high": [101.0], "low": [99.0],
            "close": [100.0], "volume": [1000000.0],
        })
        df.to_parquet(tmp_path / "feature_matrix.parquet")

        config = {
            "codes": ["SPY"],
            "start_date": "2024-01-01",
            "end_date": "2024-01-01",
            "initial_cash": 100000,
            "feature_matrix_path": str(tmp_path / "feature_matrix.parquet"),
            "params": {},
        }
        config_path = tmp_path / "config.json"
        config_path.write_text(json.dumps(config))

        result = subprocess.run(
            [sys.executable, "tools/backtest_tool.py",
             "--engine", "global_equity",
             "--config", str(config_path),
             "--dry-run"],
            capture_output=True,
            text=True,
            cwd=Path(__file__).resolve().parents[2],
        )
        assert result.returncode == 0
        out = json.loads(result.stdout)
        assert out["status"] == "ok"


def test_backtest_tool_validate_config_missing_field():
    """Config missing required field should return CONFIG_INVALID."""
    with tempfile.TemporaryDirectory() as tmp:
        tmp_path = Path(tmp)
        config = {"initial_cash": 100000}  # missing codes, start_date, etc.
        config_path = tmp_path / "config.json"
        config_path.write_text(json.dumps(config))

        result = subprocess.run(
            [sys.executable, "tools/backtest_tool.py",
             "--engine", "global_equity",
             "--config", str(config_path),
             "--dry-run"],
            capture_output=True,
            text=True,
            cwd=Path(__file__).resolve().parents[2],
        )
        assert result.returncode != 0
        err = json.loads(result.stderr)
        assert err["error_type"] == "CONFIG_INVALID"


def test_backtest_tool_unsupported_engine():
    """Unsupported engine should return UNSUPPORTED_STRATEGY."""
    with tempfile.TemporaryDirectory() as tmp:
        tmp_path = Path(tmp)
        config = {"codes": ["SPY"], "start_date": "2024-01-01", "end_date": "2024-01-01", "initial_cash": 100000}
        config_path = tmp_path / "config.json"
        config_path.write_text(json.dumps(config))

        result = subprocess.run(
            [sys.executable, "tools/backtest_tool.py",
             "--engine", "crypto",
             "--config", str(config_path),
             "--dry-run"],
            capture_output=True,
            text=True,
            cwd=Path(__file__).resolve().parents[2],
        )
        assert result.returncode != 0
        err = json.loads(result.stderr)
        assert err["error_type"] == "UNSUPPORTED_STRATEGY"
