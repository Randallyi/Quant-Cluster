#!/usr/bin/env python3
"""CLI wrapper for backtest engines.

Agents call this script to execute backtests:

    python3 tools/backtest_tool.py --engine global_equity --config config.json --out-dir /workspace/03_backtest/
    python3 tools/backtest_tool.py --engine global_equity --config config.json --dry-run
    python3 tools/backtest_tool.py --engine global_equity --schema
"""

from __future__ import annotations

import argparse
import json
import sys
import traceback
from pathlib import Path

# Allow importing from project root
_PROJECT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(_PROJECT_ROOT))

import pandas as pd


# ─── Schema definitions ──────────────────────────────────────────────────────

_SCHEMAS = {
    "global_equity": {
        "engine": "global_equity",
        "required_fields": ["codes", "start_date", "end_date", "initial_cash", "feature_matrix_path"],
        "optional_fields": ["interval", "leverage", "slippage_us", "slippage_hk", "hk_stamp_tax",
                            "hk_commission", "hk_levy", "hk_settlement", "benchmark",
                            "optimizer", "optimizer_params", "validation", "market"],
    },
    "options_portfolio": {
        "engine": "options_portfolio",
        "required_fields": ["codes", "start_date", "end_date", "initial_cash", "feature_matrix_path"],
        "optional_fields": ["interval", "commission", "options_config", "signals"],
    },
}


# ─── Error helpers ───────────────────────────────────────────────────────────

class BacktestToolError(Exception):
    """Structured error for the CLI tool."""

    def __init__(
        self,
        error_type: str,
        message: str,
        suggestion: str = "",
        retryable: bool = False,
        field: str = "",
    ):
        self.error_type = error_type
        self.message = message
        self.suggestion = suggestion
        self.retryable = retryable
        self.field = field
        super().__init__(message)

    def to_dict(self) -> dict:
        return {
            "error_type": self.error_type,
            "message": self.message,
            "suggestion": self.suggestion,
            "retryable": self.retryable,
            "field": self.field,
        }


def _die(err: BacktestToolError) -> None:
    sys.stderr.write(json.dumps(err.to_dict(), ensure_ascii=False, indent=2) + "\n")
    sys.exit(1)


def _die_unexpected(exc: Exception) -> None:
    err = BacktestToolError(
        error_type="RUNTIME_ERROR",
        message=str(exc),
        suggestion="Check the traceback and report if persistent.",
        retryable=True,
    )
    sys.stderr.write(json.dumps(err.to_dict(), ensure_ascii=False, indent=2) + "\n")
    sys.exit(1)


# ─── Config validation ───────────────────────────────────────────────────────

def _load_config(config_path: str) -> dict:
    p = Path(config_path)
    if not p.exists():
        raise BacktestToolError(
            error_type="DATA_NOT_FOUND",
            message=f"Config file not found: {config_path}",
            suggestion="Verify the config path and try again.",
            retryable=True,
            field="config",
        )
    try:
        with p.open("r", encoding="utf-8") as fh:
            return json.load(fh)
    except json.JSONDecodeError as exc:
        raise BacktestToolError(
            error_type="CONFIG_INVALID",
            message=f"Invalid JSON in config file: {exc}",
            suggestion="Fix JSON syntax and retry.",
            retryable=True,
            field="config",
        )


def _validate_config(engine: str, config: dict) -> None:
    schema = _SCHEMAS.get(engine)
    if schema is None:
        raise BacktestToolError(
            error_type="UNSUPPORTED_STRATEGY",
            message=f"Engine '{engine}' is not supported.",
            suggestion=f"Supported engines: {', '.join(_SCHEMAS)}.",
            retryable=False,
            field="engine",
        )

    missing = [f for f in schema["required_fields"] if f not in config]
    if missing:
        raise BacktestToolError(
            error_type="CONFIG_INVALID",
            message=f"Missing required fields: {', '.join(missing)}",
            suggestion="Provide all required fields in the config JSON.",
            retryable=True,
            field=missing[0],
        )


# ─── Data loading ────────────────────────────────────────────────────────────

def _load_data_map(config: dict) -> dict[str, pd.DataFrame]:
    path = Path(config["feature_matrix_path"])
    if not path.exists():
        raise BacktestToolError(
            error_type="DATA_NOT_FOUND",
            message=f"Feature matrix not found: {path}",
            suggestion="Check feature_matrix_path in config.",
            retryable=True,
            field="feature_matrix_path",
        )

    try:
        df = pd.read_parquet(path)
    except Exception as exc:
        raise BacktestToolError(
            error_type="DATA_NOT_FOUND",
            message=f"Failed to read parquet: {exc}",
            suggestion="Ensure the file is a valid parquet file.",
            retryable=True,
            field="feature_matrix_path",
        )

    # Multi-symbol detection
    if "symbol" in df.columns:
        return {sym: group.drop(columns=["symbol"]) for sym, group in df.groupby("symbol")}
    if "code" in df.columns:
        return {sym: group.drop(columns=["code"]) for sym, group in df.groupby("code")}

    codes = config.get("codes", [])
    if isinstance(codes, list) and len(codes) == 1:
        return {codes[0]: df}

    # Try MultiIndex columns (symbol, field)
    if isinstance(df.columns, pd.MultiIndex):
        symbols = df.columns.get_level_values(0).unique().tolist()
        return {sym: df[sym].copy() for sym in symbols}

    # Single-symbol fallback
    return {"_single": df}


# ─── Signal computation (Phase 1 minimal) ────────────────────────────────────

def _build_signal_map(engine: str, config: dict, data_map: dict[str, pd.DataFrame]) -> dict | list:
    raw_signals = config.get("signals")

    if engine == "global_equity":
        signal_map: dict[str, pd.Series] = {}
        if isinstance(raw_signals, dict):
            for code, values in raw_signals.items():
                if code in data_map:
                    idx = data_map[code].index
                    if isinstance(values, list) and len(values) == len(idx):
                        signal_map[code] = pd.Series(values, index=idx)
                    else:
                        signal_map[code] = pd.Series(float(values), index=idx)
        # Fill missing codes with neutral pass-through (1.0)
        for code, df in data_map.items():
            if code not in signal_map:
                signal_map[code] = pd.Series(1.0, index=df.index)
        return signal_map

    if engine == "options_portfolio":
        if isinstance(raw_signals, list):
            return raw_signals
        return []

    raise BacktestToolError(
        error_type="UNSUPPORTED_STRATEGY",
        message=f"Signal computation for engine '{engine}' is not supported.",
        suggestion=f"Supported engines: {', '.join(_SCHEMAS)}.",
        retryable=False,
        field="engine",
    )


# ─── Engine invocation ───────────────────────────────────────────────────────

def _run_engine(
    engine: str,
    config: dict,
    data_map: dict[str, pd.DataFrame],
    signal_map: dict | list,
    run_dir: Path,
) -> dict:
    if engine == "global_equity":
        from backtest.engines.global_equity import GlobalEquityEngine

        market = config.get("market", "us")
        eng = GlobalEquityEngine(config, market=market)
        return eng.run_backtest(
            config=config,
            data_map=data_map,
            signal_map=signal_map,  # type: ignore[arg-type]
            run_dir=run_dir,
            bars_per_year=config.get("bars_per_year", 252),
        )

    if engine == "options_portfolio":
        from backtest.engines.options_portfolio import run_options_backtest

        return run_options_backtest(
            config=config,
            data_map=data_map,
            signal_map=signal_map,  # type: ignore[arg-type]
            run_dir=run_dir,
            bars_per_year=config.get("bars_per_year", 252),
        )

    raise BacktestToolError(
        error_type="UNSUPPORTED_STRATEGY",
        message=f"Engine '{engine}' is not supported.",
        suggestion=f"Supported engines: {', '.join(_SCHEMAS)}.",
        retryable=False,
        field="engine",
    )


# ─── CLI ─────────────────────────────────────────────────────────────────────

def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Backtest engine CLI wrapper")
    parser.add_argument("--engine", required=True, choices=list(_SCHEMAS), help="Backtest engine to use")
    parser.add_argument("--config", type=str, default=None, help="Path to config JSON file")
    parser.add_argument("--out-dir", type=str, default=None, help="Output directory for run artifacts")
    parser.add_argument("--dry-run", action="store_true", help="Validate config and data without running")
    parser.add_argument("--schema", action="store_true", help="Print engine schema JSON and exit")
    return parser


def main(argv: list[str] | None = None) -> int:
    parser = _build_parser()
    args = parser.parse_args(argv)

    # Schema mode
    if args.schema:
        schema = _SCHEMAS.get(args.engine)
        if schema is None:
            err = BacktestToolError(
                error_type="UNSUPPORTED_STRATEGY",
                message=f"Engine '{args.engine}' is not supported.",
                suggestion=f"Supported engines: {', '.join(_SCHEMAS)}.",
                retryable=False,
                field="engine",
            )
            _die(err)
        print(json.dumps(schema, indent=2))
        return 0

    # Config is required for non-schema modes
    if not args.config:
        err = BacktestToolError(
            error_type="CONFIG_INVALID",
            message="--config is required when not using --schema",
            suggestion="Provide a JSON config file path via --config.",
            retryable=True,
            field="config",
        )
        _die(err)

    # Load and validate config
    config = _load_config(args.config)
    _validate_config(args.engine, config)

    # Load data
    data_map = _load_data_map(config)

    # Build signals
    signal_map = _build_signal_map(args.engine, config, data_map)

    # Dry-run: stop here
    if args.dry_run:
        dry_result = {
            "dry_run": True,
            "engine": args.engine,
            "config_path": args.config,
            "data_symbols": list(data_map.keys()),
            "signal_summary": (
                {k: "Series" for k in signal_map} if isinstance(signal_map, dict) else f"{len(signal_map)} trade(s)"
            ),
        }
        print(json.dumps(dry_result, indent=2))
        return 0

    # Determine run_dir
    if args.out_dir:
        run_dir = Path(args.out_dir)
    else:
        # Default to a timestamped subdirectory under the shared workspace
        from datetime import datetime

        ts = datetime.now().strftime("%Y%m%d_%H%M%S")
        run_dir = _PROJECT_ROOT / "shared_workspace" / "03_backtest" / f"run_{ts}"
    run_dir.mkdir(parents=True, exist_ok=True)

    # Run engine
    metrics = _run_engine(args.engine, config, data_map, signal_map, run_dir)

    # The engines already call write_run_card internally, but we ensure it is called
    # explicitly here as well in case a future engine skips it.
    from backtest.engines.run_card import write_run_card

    write_run_card(
        run_dir=run_dir,
        config=config,
        metrics=metrics,
        data_sources=[config.get("source", "")],
        strategy_path=run_dir / "code" / "signal_engine.py",
    )

    # Print metrics to stdout
    print(json.dumps({k: v for k, v in metrics.items() if not isinstance(v, dict)}, indent=2))
    return 0


if __name__ == "__main__":
    try:
        sys.exit(main())
    except BacktestToolError as exc:
        _die(exc)
    except Exception as exc:
        _die_unexpected(exc)
