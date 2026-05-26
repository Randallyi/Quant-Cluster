"""Backtest metrics calculation utilities."""

from __future__ import annotations

from typing import Any, Dict, List

import numpy as np
import pandas as pd


def calc_metrics(
    equity_series: pd.Series,
    trades: List[Any],
    initial_capital: float,
    bars_per_year: int = 252,
    benchmark_ret: pd.Series | None = None,
) -> Dict[str, Any]:
    """Calculate backtest performance metrics.

    Args:
        equity_series: Equity curve time series.
        trades: List of completed TradeRecord objects.
        initial_capital: Starting capital.
        bars_per_year: Annualisation factor.
        benchmark_ret: Optional benchmark return series.

    Returns:
        Dict of scalar metrics.
    """
    if len(equity_series) < 2:
        return {"sharpe": 0.0, "num_trades": len(trades)}

    returns = equity_series.pct_change().dropna().values
    if len(returns) == 0:
        return {"sharpe": 0.0, "num_trades": len(trades)}

    std = returns.std()
    sharpe = float(returns.mean() / (std + 1e-10) * np.sqrt(bars_per_year))

    peak = equity_series.cummax()
    dd = (equity_series - peak) / peak.replace(0, 1)
    max_dd = float(dd.min())

    total_ret = float(equity_series.iloc[-1] / initial_capital - 1) if initial_capital > 0 else 0.0

    win_count = sum(1 for t in trades if getattr(t, "pnl", 0) > 0)
    num_trades = len(trades)
    win_rate = win_count / num_trades if num_trades > 0 else 0.0

    total_pnl = sum(getattr(t, "pnl", 0.0) for t in trades)
    total_commission = sum(getattr(t, "commission", 0.0) for t in trades)

    result = {
        "sharpe": round(sharpe, 4),
        "max_drawdown": round(max_dd, 6),
        "total_return": round(total_ret, 6),
        "num_trades": num_trades,
        "win_rate": round(win_rate, 4),
        "total_pnl": round(total_pnl, 4),
        "total_commission": round(total_commission, 4),
    }

    if benchmark_ret is not None and len(benchmark_ret) > 0:
        bench_equity = initial_capital * (1 + benchmark_ret.reindex(equity_series.index).fillna(0.0)).cumprod()
        if len(bench_equity) > 1 and bench_equity.iloc[0] > 0:
            active_ret = equity_series.pct_change().fillna(0.0) - benchmark_ret.reindex(equity_series.index).fillna(0.0)
            active_vals = active_ret.values
            if len(active_vals) > 0:
                active_std = active_vals.std()
                result["information_ratio"] = round(
                    float(active_vals.mean() / (active_std + 1e-10) * np.sqrt(bars_per_year)), 4
                )

    return result


def by_symbol_stats(trades: List[Any]) -> Dict[str, Any]:
    """Aggregate statistics grouped by symbol.

    Args:
        trades: List of completed TradeRecord objects.

    Returns:
        Dict keyed by symbol with per-symbol stats.
    """
    from collections import defaultdict

    by_sym: Dict[str, List[Any]] = defaultdict(list)
    for t in trades:
        by_sym[getattr(t, "symbol", "")].append(t)

    result: Dict[str, Any] = {}
    for sym, sym_trades in by_sym.items():
        pnls = [getattr(t, "pnl", 0.0) for t in sym_trades]
        wins = [p for p in pnls if p > 0]
        result[sym] = {
            "num_trades": len(sym_trades),
            "win_rate": round(len(wins) / len(pnls), 4) if pnls else 0.0,
            "total_pnl": round(sum(pnls), 4),
            "avg_pnl": round(sum(pnls) / len(pnls), 4) if pnls else 0.0,
        }
    return result


def by_exit_reason_stats(trades: List[Any]) -> Dict[str, Any]:
    """Aggregate statistics grouped by exit reason.

    Args:
        trades: List of completed TradeRecord objects.

    Returns:
        Dict keyed by exit reason with per-reason stats.
    """
    from collections import defaultdict

    by_reason: Dict[str, List[Any]] = defaultdict(list)
    for t in trades:
        by_reason[getattr(t, "exit_reason", "")].append(t)

    result: Dict[str, Any] = {}
    for reason, reason_trades in by_reason.items():
        pnls = [getattr(t, "pnl", 0.0) for t in reason_trades]
        wins = [p for p in pnls if p > 0]
        result[reason] = {
            "num_trades": len(reason_trades),
            "win_rate": round(len(wins) / len(pnls), 4) if pnls else 0.0,
            "total_pnl": round(sum(pnls), 4),
            "avg_pnl": round(sum(pnls) / len(pnls), 4) if pnls else 0.0,
        }
    return result
