import subprocess
import sys
import json
from pathlib import Path


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
