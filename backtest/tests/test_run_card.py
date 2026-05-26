import json
import pytest
from pathlib import Path
from backtest.engines.run_card import write_run_card


def test_write_run_card(tmp_path):
    run_dir = tmp_path / "run_001"
    run_dir.mkdir()

    # Write a dummy config.json
    config = {"codes": ["SPY"], "start_date": "2024-01-01", "end_date": "2024-01-30"}
    (run_dir / "config.json").write_text(json.dumps(config))

    metrics = {"sharpe": 1.5, "max_drawdown": -0.05}

    card = write_run_card(
        run_dir=run_dir,
        config=config,
        metrics=metrics,
        data_sources=["yfinance"],
    )

    assert card["schema_version"] == "0.1"
    assert card["metrics"]["sharpe"] == 1.5
    assert "generated_at" in card

    json_path = run_dir / "run_card.json"
    md_path = run_dir / "run_card.md"
    assert json_path.exists()
    assert md_path.exists()

    loaded = json.loads(json_path.read_text())
    assert loaded["data_sources"] == ["yfinance"]
    assert "config_hash" in loaded["reproducibility"]
