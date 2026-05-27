#!/usr/bin/env python3
"""CLI wrapper for factor library."""

from __future__ import annotations

import argparse
import json
import sys
import traceback
from pathlib import Path

import pandas as pd
import numpy as np

_PROJECT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(_PROJECT_ROOT))

from factors.registry import list_factors, compute
from factors.bench_runner import evaluate


# ─── Error helpers ───────────────────────────────────────────────────────────

class FactorToolError(Exception):
    def __init__(self, error_type: str, message: str, suggestion: str = "", retryable: bool = False):
        self.error_type = error_type
        self.message = message
        self.suggestion = suggestion
        self.retryable = retryable
        super().__init__(message)

    def to_dict(self) -> dict:
        return {"error_type": self.error_type, "message": self.message, "suggestion": self.suggestion, "retryable": self.retryable}


def _die(err: FactorToolError) -> None:
    sys.stderr.write(json.dumps(err.to_dict(), ensure_ascii=False, indent=2) + "\n")
    sys.exit(1)


def _die_unexpected(exc: Exception) -> None:
    err = FactorToolError(error_type="RUNTIME_ERROR", message=str(exc), suggestion="Check the traceback and report if persistent.", retryable=True)
    sys.stderr.write(json.dumps(err.to_dict(), ensure_ascii=False, indent=2) + "\n")
    sys.exit(1)


# ─── Data loading ────────────────────────────────────────────────────────────

def _load_panel(path: str) -> pd.DataFrame:
    p = Path(path)
    if not p.exists():
        raise FactorToolError(error_type="DATA_NOT_FOUND", message=f"Data file not found: {path}", suggestion="Verify the data path.", retryable=True)
    try:
        df = pd.read_parquet(p)
    except Exception as exc:
        raise FactorToolError(error_type="DATA_NOT_FOUND", message=f"Failed to read parquet: {exc}", suggestion="Ensure the file is a valid parquet file.", retryable=True)

    if not isinstance(df.columns, pd.MultiIndex):
        if len(df.columns) > 0 and isinstance(df.columns[0], tuple):
            df.columns = pd.MultiIndex.from_tuples(df.columns)
        else:
            raise FactorToolError(error_type="DATA_NOT_FOUND", message="Data columns must be MultiIndex (symbol, field)", suggestion="Use ohlcv_panel.parquet format with MultiIndex columns.", retryable=True)
    return df


def _extract_fields(df: pd.DataFrame) -> dict[str, pd.DataFrame]:
    fields = df.columns.get_level_values(1).unique()
    return {field: df.xs(field, level=1, axis=1) for field in fields}


# ─── Signal generation ───────────────────────────────────────────────────────

def _build_signal(factor_name: str, data: dict[str, pd.DataFrame], params: dict) -> pd.DataFrame:
    factor_df = compute(factor_name, data)
    if isinstance(factor_df.columns, pd.MultiIndex):
        output_col = factor_df.columns.get_level_values(0)[0]
        factor_values = factor_df[output_col]
    else:
        output_col = factor_df.columns[0]
        factor_values = factor_df[output_col]
        if isinstance(factor_values, pd.Series):
            factor_values = factor_values.to_frame()

    direction = params.get("direction", "long_short")
    top_pct = params.get("top_pct", 0.2)
    bottom_pct = params.get("bottom_pct", 0.2)

    rank_df = factor_values.rank(axis=1, pct=True, ascending=True)
    signals = pd.DataFrame(0.0, index=rank_df.index, columns=rank_df.columns)

    for date in rank_df.index:
        row = rank_df.loc[date].dropna()
        if len(row) == 0:
            continue
        n = len(row)
        top_n = max(1, int(n * top_pct))
        bottom_n = max(1, int(n * bottom_pct))
        top_syms = row.nlargest(top_n).index if direction in ("long_only", "long_short") else []
        bottom_syms = row.nsmallest(bottom_n).index if direction in ("short_only", "long_short") else []
        if direction in ("long_only", "long_short"):
            signals.loc[date, top_syms] = 1.0 / len(top_syms) if len(top_syms) > 0 else 0.0
        if direction in ("short_only", "long_short"):
            signals.loc[date, bottom_syms] = -1.0 / len(bottom_syms) if len(bottom_syms) > 0 else 0.0

    scale = signals.abs().sum(axis=1).clip(lower=1.0)
    return signals.div(scale, axis=0)


def _build_combined_signal(factor_names: list[str], weights: list[float], data: dict[str, pd.DataFrame], params: dict) -> pd.DataFrame:
    combined = None
    for name, w in zip(factor_names, weights):
        sig = _build_signal(name, data, params)
        if combined is None:
            combined = sig * w
        else:
            combined = combined.add(sig * w, fill_value=0.0)
    scale = combined.abs().sum(axis=1).clip(lower=1.0)
    return combined.div(scale, axis=0)


# ─── Actions ─────────────────────────────────────────────────────────────────

def _action_list(args: argparse.Namespace) -> int:
    factors = list_factors(category=args.category)
    print(json.dumps({"factors": factors}, indent=2))
    return 0


def _action_bench(args: argparse.Namespace) -> int:
    if not args.data:
        raise FactorToolError(error_type="CONFIG_INVALID", message="--data is required for bench", suggestion="Provide --data path", retryable=True)
    if not args.factor:
        raise FactorToolError(error_type="CONFIG_INVALID", message="--factor is required for bench", suggestion="Provide --factor name", retryable=True)
    if not args.dry_run and not args.out_dir:
        raise FactorToolError(error_type="CONFIG_INVALID", message="--out-dir is required for bench", suggestion="Provide --out-dir path", retryable=True)

    df = _load_panel(args.data)
    data = _extract_fields(df)

    factors_list = list_factors()
    factor_names = [f["name"] for f in factors_list]
    if args.factor not in factor_names:
        raise FactorToolError(error_type="UNSUPPORTED_FACTOR", message=f"Factor not found: {args.factor}", suggestion=f"Available: {', '.join(factor_names)}", retryable=False)

    meta = next(f for f in factors_list if f["name"] == args.factor)
    missing = set(meta["inputs"]) - set(data.keys())
    if missing:
        raise FactorToolError(error_type="DATA_NOT_FOUND", message=f"Missing inputs for {args.factor}: {sorted(missing)}", suggestion="Provide required data columns", retryable=True)

    if args.dry_run:
        print(json.dumps({"status": "ok", "dry_run": True, "factor": args.factor}, indent=2))
        return 0

    close = data.get("close")
    if close is None:
        raise FactorToolError(error_type="DATA_NOT_FOUND", message="close field required for forward returns", suggestion="Ensure data has close field", retryable=True)

    factor_df = compute(args.factor, data)
    fwd_ret = close.pct_change(args.fwd_days).shift(-args.fwd_days)

    if len(factor_df.columns) == 1:
        factor_series = factor_df.iloc[:, 0]
        fwd_series = fwd_ret.iloc[:, 0] if len(fwd_ret.columns) == 1 else fwd_ret.stack()
    else:
        stacked = factor_df.stack()
        if isinstance(stacked, pd.DataFrame):
            factor_series = stacked.iloc[:, 0]
        else:
            factor_series = stacked
        fwd_series = fwd_ret.stack()

    result = evaluate(factor_series, fwd_series, fwd_days=args.fwd_days)

    out_dir = Path(args.out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)

    json_path = out_dir / f"factor_bench_{args.factor}.json"
    md_path = out_dir / f"factor_bench_{args.factor}.md"

    with open(json_path, "w") as f:
        json.dump(result, f, indent=2, default=str)

    with open(md_path, "w") as f:
        f.write(f"# Factor Benchmark: {args.factor}\n\n")
        f.write(f"- **IC**: {result['ic']:.4f}\n")
        f.write(f"- **IC IR**: {result['ic_ir']:.4f}\n")
        f.write(f"- **Rank IC**: {result['rank_ic']:.4f}\n")
        f.write(f"- **Rank IC IR**: {result['rank_ic_ir']:.4f}\n")
        f.write(f"- **Classification**: {result['classification']}\n")
        f.write(f"- **Turnover**: {result['turnover']:.4f}\n")
        f.write(f"- **Forward Days**: {result['fwd_days']}\n")
        f.write(f"- **N Obs**: {result['n_obs']}\n")

    scalar = {k: v for k, v in result.items() if not isinstance(v, (list, pd.Series, pd.DataFrame, dict))}
    print(json.dumps(scalar, indent=2))
    return 0


def _action_bench_category(args: argparse.Namespace) -> int:
    if not args.data:
        raise FactorToolError(error_type="CONFIG_INVALID", message="--data is required for bench_category", suggestion="Provide --data path", retryable=True)
    if not args.category:
        raise FactorToolError(error_type="CONFIG_INVALID", message="--category is required for bench_category", suggestion="Provide --category name", retryable=True)
    if not args.out_dir:
        raise FactorToolError(error_type="CONFIG_INVALID", message="--out-dir is required for bench_category", suggestion="Provide --out-dir path", retryable=True)

    df = _load_panel(args.data)
    data = _extract_fields(df)
    close = data.get("close")
    if close is None:
        raise FactorToolError(error_type="DATA_NOT_FOUND", message="close field required for forward returns", suggestion="Ensure data has close field", retryable=True)

    factors_list = list_factors(category=args.category)
    if not factors_list:
        raise FactorToolError(error_type="UNSUPPORTED_FACTOR", message=f"No factors in category: {args.category}", suggestion="Check available categories", retryable=False)

    out_dir = Path(args.out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)

    results = {}
    for meta in factors_list:
        name = meta["name"]
        missing = set(meta["inputs"]) - set(data.keys())
        if missing:
            continue

        factor_df = compute(name, data)
        fwd_ret = close.pct_change(args.fwd_days).shift(-args.fwd_days)

        if len(factor_df.columns) == 1:
            factor_series = factor_df.iloc[:, 0]
            fwd_series = fwd_ret.iloc[:, 0] if len(fwd_ret.columns) == 1 else fwd_ret.stack()
        else:
            stacked = factor_df.stack()
            if isinstance(stacked, pd.DataFrame):
                factor_series = stacked.iloc[:, 0]
            else:
                factor_series = stacked
            fwd_series = fwd_ret.stack()

        result = evaluate(factor_series, fwd_series, fwd_days=args.fwd_days)
        results[name] = result

    summary_path = out_dir / f"bench_summary_{args.category}.json"
    with open(summary_path, "w") as f:
        json.dump(results, f, indent=2, default=str)

    print(json.dumps({"status": "ok", "results": len(results), "summary_path": str(summary_path)}, indent=2))
    return 0


def _action_signal(args: argparse.Namespace) -> int:
    if not args.data:
        raise FactorToolError(error_type="CONFIG_INVALID", message="--data is required for signal", suggestion="Provide --data path", retryable=True)
    if not args.out_dir:
        raise FactorToolError(error_type="CONFIG_INVALID", message="--out-dir is required for signal", suggestion="Provide --out-dir path", retryable=True)

    df = _load_panel(args.data)
    data = _extract_fields(df)

    params = {}
    if args.params:
        try:
            params = json.loads(args.params)
        except json.JSONDecodeError as exc:
            raise FactorToolError(error_type="CONFIG_INVALID", message=f"Invalid params JSON: {exc}", suggestion="Fix params JSON", retryable=True)

    if args.factors and args.weights:
        factor_names = [f.strip() for f in args.factors.split(",")]
        weights = [float(w.strip()) for w in args.weights.split(",")]
        if len(factor_names) != len(weights):
            raise FactorToolError(error_type="CONFIG_INVALID", message="--factors and --weights must have same length", suggestion="Provide matching counts", retryable=True)
        signal_df = _build_combined_signal(factor_names, weights, data, params)
    elif args.factor:
        signal_df = _build_signal(args.factor, data, params)
    else:
        raise FactorToolError(error_type="CONFIG_INVALID", message="--factor or --factors required", suggestion="Provide one of them", retryable=True)

    out_dir = Path(args.out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)

    parquet_path = out_dir / "signal.parquet"
    signal_df.to_parquet(parquet_path)

    json_path = out_dir / "signal.json"
    signal_json = {
        "signal_map": {col: [float(v) for v in signal_df[col].fillna(0.0).tolist()] for col in signal_df.columns},
        "dates": signal_df.index.strftime("%Y-%m-%d").tolist(),
    }
    with open(json_path, "w") as f:
        json.dump(signal_json, f, indent=2)

    print(json.dumps({"status": "ok", "signal_path": str(parquet_path), "json_path": str(json_path), "dates": len(signal_df), "symbols": list(signal_df.columns)}, indent=2))
    return 0


# ─── CLI parser + main ───────────────────────────────────────────────────────

def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Factor library CLI wrapper")
    parser.add_argument("--action", required=True, choices=["list", "bench", "bench_category", "signal"])
    parser.add_argument("--factor", type=str, default="")
    parser.add_argument("--factors", type=str, default="")
    parser.add_argument("--weights", type=str, default="")
    parser.add_argument("--category", type=str, default="")
    parser.add_argument("--data", type=str, default="")
    parser.add_argument("--fwd-days", type=int, default=5)
    parser.add_argument("--params", type=str, default="")
    parser.add_argument("--out-dir", type=str, default="")
    parser.add_argument("--dry-run", action="store_true")
    return parser


def main(argv: list[str] | None = None) -> int:
    parser = _build_parser()
    args = parser.parse_args(argv)
    try:
        if args.action == "list":
            return _action_list(args)
        elif args.action == "bench":
            return _action_bench(args)
        elif args.action == "bench_category":
            return _action_bench_category(args)
        elif args.action == "signal":
            return _action_signal(args)
    except FactorToolError as exc:
        _die(exc)
    except Exception as exc:
        _die_unexpected(exc)
    return 0


if __name__ == "__main__":
    sys.exit(main())
