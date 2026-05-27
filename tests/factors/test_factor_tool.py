import json
import subprocess
import sys
from pathlib import Path

import numpy as np
import pandas as pd
import pytest

PROJECT_ROOT = Path(__file__).resolve().parents[2]
FACTOR_TOOL = PROJECT_ROOT / "tools" / "factor_tool.py"


@pytest.fixture
def sample_ohlcv_panel(tmp_path):
    dates = pd.date_range("2023-01-01", periods=100, freq="D")
    symbols = ["SPY", "QQQ"]
    np.random.seed(42)

    data = {}
    for sym in symbols:
        base = 100 + np.cumsum(np.random.randn(100) * 0.5)
        data[(sym, "open")] = base + np.random.randn(100) * 0.1
        data[(sym, "high")] = base + abs(np.random.randn(100)) * 0.2
        data[(sym, "low")] = base - abs(np.random.randn(100)) * 0.2
        data[(sym, "close")] = base
        data[(sym, "volume")] = np.random.randint(1_000_000, 10_000_000, 100)

    df = pd.DataFrame(data, index=dates)
    df.columns = pd.MultiIndex.from_tuples(df.columns)

    panel_path = tmp_path / "ohlcv_panel.parquet"
    df.to_parquet(panel_path)
    return str(panel_path)


class TestFactorToolList:
    def test_list_action(self):
        cmd = [
            sys.executable,
            str(FACTOR_TOOL),
            "--action",
            "list",
        ]
        result = subprocess.run(cmd, capture_output=True, text=True)
        assert result.returncode == 0, result.stderr
        out = json.loads(result.stdout)
        assert "factors" in out
        names = [f["name"] for f in out["factors"]]
        assert "academic_carhart_mom" in names

    def test_list_filter_category(self):
        cmd = [
            sys.executable,
            str(FACTOR_TOOL),
            "--action",
            "list",
            "--category",
            "academic",
        ]
        result = subprocess.run(cmd, capture_output=True, text=True)
        assert result.returncode == 0, result.stderr
        out = json.loads(result.stdout)
        assert all(f["category"] == "academic" for f in out["factors"])


class TestFactorToolBench:
    def test_bench_single_factor(self, sample_ohlcv_panel, tmp_path):
        out_dir = tmp_path / "bench_out"
        cmd = [
            sys.executable,
            str(FACTOR_TOOL),
            "--action",
            "bench",
            "--factor",
            "academic_carhart_mom",
            "--data",
            sample_ohlcv_panel,
            "--fwd-days",
            "5",
            "--out-dir",
            str(out_dir),
        ]
        result = subprocess.run(cmd, capture_output=True, text=True)
        assert result.returncode == 0, result.stderr
        json_path = out_dir / "factor_bench_academic_carhart_mom.json"
        md_path = out_dir / "factor_bench_academic_carhart_mom.md"
        assert json_path.exists()
        assert md_path.exists()
        with open(json_path) as f:
            data = json.load(f)
        assert "ic" in data
        assert "classification" in data

    def test_bench_category(self, sample_ohlcv_panel, tmp_path):
        out_dir = tmp_path / "bench_cat_out"
        cmd = [
            sys.executable,
            str(FACTOR_TOOL),
            "--action",
            "bench_category",
            "--category",
            "academic",
            "--data",
            sample_ohlcv_panel,
            "--out-dir",
            str(out_dir),
        ]
        result = subprocess.run(cmd, capture_output=True, text=True)
        assert result.returncode == 0, result.stderr
        summary_path = out_dir / "bench_summary_academic.json"
        assert summary_path.exists()

    def test_bench_dry_run(self, sample_ohlcv_panel, tmp_path):
        cmd = [
            sys.executable,
            str(FACTOR_TOOL),
            "--action",
            "bench",
            "--factor",
            "academic_carhart_mom",
            "--data",
            sample_ohlcv_panel,
            "--dry-run",
        ]
        result = subprocess.run(cmd, capture_output=True, text=True)
        assert result.returncode == 0, result.stderr
        out = json.loads(result.stdout)
        assert out["status"] == "ok"


class TestFactorToolSignal:
    def test_signal_single_factor(self, sample_ohlcv_panel, tmp_path):
        out_dir = tmp_path / "signal_out"
        cmd = [
            sys.executable,
            str(FACTOR_TOOL),
            "--action",
            "signal",
            "--factor",
            "academic_carhart_mom",
            "--data",
            sample_ohlcv_panel,
            "--params",
            '{"direction":"long_short","top_pct":0.2}',
            "--out-dir",
            str(out_dir),
        ]
        result = subprocess.run(cmd, capture_output=True, text=True)
        assert result.returncode == 0, result.stderr
        json_path = out_dir / "signal.json"
        parquet_path = out_dir / "signal.parquet"
        assert json_path.exists()
        assert parquet_path.exists()
        with open(json_path) as f:
            data = json.load(f)
        assert "signal_map" in data
        assert "dates" in data

    def test_signal_multi_factor(self, sample_ohlcv_panel, tmp_path):
        out_dir = tmp_path / "signal_multi_out"
        cmd = [
            sys.executable,
            str(FACTOR_TOOL),
            "--action",
            "signal",
            "--factors",
            "academic_carhart_mom,academic_hml",
            "--weights",
            "0.6,0.4",
            "--data",
            sample_ohlcv_panel,
            "--params",
            '{"direction":"long_short","top_pct":0.2}',
            "--out-dir",
            str(out_dir),
        ]
        result = subprocess.run(cmd, capture_output=True, text=True)
        assert result.returncode == 0, result.stderr
        json_path = out_dir / "signal.json"
        parquet_path = out_dir / "signal.parquet"
        assert json_path.exists()
        assert parquet_path.exists()


class TestFactorToolErrors:
    def test_unknown_factor(self, sample_ohlcv_panel, tmp_path):
        cmd = [
            sys.executable,
            str(FACTOR_TOOL),
            "--action",
            "bench",
            "--factor",
            "unknown_factor",
            "--data",
            sample_ohlcv_panel,
            "--out-dir",
            str(tmp_path),
        ]
        result = subprocess.run(cmd, capture_output=True, text=True)
        assert result.returncode != 0
        err = json.loads(result.stderr)
        assert err["error_type"] == "UNSUPPORTED_FACTOR"

    def test_missing_data_columns(self, tmp_path):
        dates = pd.date_range("2023-01-01", periods=100, freq="D")
        symbols = ["SPY", "QQQ"]
        data = {}
        for sym in symbols:
            data[(sym, "open")] = np.random.randn(100)
        df = pd.DataFrame(data, index=dates)
        df.columns = pd.MultiIndex.from_tuples(df.columns)
        panel_path = tmp_path / "no_close.parquet"
        df.to_parquet(panel_path)

        cmd = [
            sys.executable,
            str(FACTOR_TOOL),
            "--action",
            "bench",
            "--factor",
            "academic_carhart_mom",
            "--data",
            str(panel_path),
            "--out-dir",
            str(tmp_path),
        ]
        result = subprocess.run(cmd, capture_output=True, text=True)
        assert result.returncode != 0
        err = json.loads(result.stderr)
        assert err["error_type"] == "DATA_NOT_FOUND"
