"""Factor evaluation: IC/IR computation and alive/reversed/dead classification."""

from __future__ import annotations

import numpy as np
import pandas as pd
from scipy import stats


def _factor_turnover(factor_values: pd.Series) -> float:
    """Compute factor turnover: mean absolute change per period."""
    turnover = factor_values.diff().abs().mean()
    mean_abs = factor_values.abs().mean()
    if mean_abs > 0:
        return turnover / mean_abs
    return 0.0


def evaluate(
    factor_values: pd.Series,
    forward_returns: pd.Series,
    fwd_days: int = 5,
) -> dict:
    """Evaluate a single factor against forward returns.

    Returns dict with keys: ic, ic_ir, rank_ic, rank_ic_ir, ic_series,
    classification, turnover, fwd_days, n_obs.
    """
    aligned = pd.DataFrame({
        "factor": factor_values,
        "fwd_ret": forward_returns,
    }).dropna()

    if len(aligned) < 30:
        return {
            "ic": np.nan,
            "ic_ir": np.nan,
            "rank_ic": np.nan,
            "rank_ic_ir": np.nan,
            "ic_series": [],
            "classification": "dead",
            "turnover": _factor_turnover(factor_values),
            "fwd_days": fwd_days,
            "n_obs": len(aligned),
        }

    f = aligned["factor"].values
    r = aligned["fwd_ret"].values

    ic = np.corrcoef(f, r)[0, 1]
    if np.isnan(ic):
        ic = 0.0

    # Rolling IC series (63-day window, min 20 obs)
    ic_series = []
    for i in range(len(aligned)):
        start = max(0, i - 62)
        if i - start + 1 >= 20:
            window_f = aligned["factor"].iloc[start:i + 1]
            window_r = aligned["fwd_ret"].iloc[start:i + 1]
            valid = window_f.notna() & window_r.notna()
            if valid.sum() >= 20:
                w_ic = np.corrcoef(window_f[valid], window_r[valid])[0, 1]
                ic_series.append(float(w_ic) if not np.isnan(w_ic) else 0.0)
            else:
                ic_series.append(0.0)
        else:
            ic_series.append(0.0)

    ic_std = np.std(ic_series) if len(ic_series) > 1 else 0.0
    ic_ir = ic / ic_std if ic_std > 1e-9 else 0.0

    rank_ic, _ = stats.spearmanr(f, r)
    if np.isnan(rank_ic):
        rank_ic = 0.0

    rank_ic_series = []
    for i in range(len(aligned)):
        start = max(0, i - 62)
        if i - start + 1 >= 20:
            window_f = aligned["factor"].iloc[start:i + 1]
            window_r = aligned["fwd_ret"].iloc[start:i + 1]
            valid = window_f.notna() & window_r.notna()
            if valid.sum() >= 20:
                w_rank_ic, _ = stats.spearmanr(window_f[valid], window_r[valid])
                rank_ic_series.append(float(w_rank_ic) if not np.isnan(w_rank_ic) else 0.0)
            else:
                rank_ic_series.append(0.0)
        else:
            rank_ic_series.append(0.0)

    rank_ic_std = np.std(rank_ic_series) if len(rank_ic_series) > 1 else 0.0
    rank_ic_ir = rank_ic / rank_ic_std if rank_ic_std > 1e-9 else 0.0

    abs_ic = abs(ic)
    abs_ir = abs(ic_ir)
    if abs_ic > 0.03 and abs_ir > 0.3:
        classification = "alive" if ic > 0 else "reversed"
    elif abs_ic < 0.02 or abs_ir < 0.2:
        classification = "dead"
    else:
        classification = "weak"

    return {
        "ic": float(ic),
        "ic_ir": float(ic_ir),
        "rank_ic": float(rank_ic),
        "rank_ic_ir": float(rank_ic_ir),
        "ic_series": ic_series,
        "classification": classification,
        "turnover": _factor_turnover(factor_values),
        "fwd_days": fwd_days,
        "n_obs": len(aligned),
    }
