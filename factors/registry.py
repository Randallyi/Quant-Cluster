"""Global factor registry with lazy compute dispatch."""

from __future__ import annotations

import pandas as pd

from factors.core.meta import REGISTRY, FactorMeta

# Auto-register all zoo modules on import
from factors.zoo_adapter import register_all_zoos

register_all_zoos()


def list_factors(category: str = "") -> list[dict]:
    """Return metadata for all registered factors.

    Args:
        category: If provided, filter by this category.

    Returns:
        List of factor metadata dicts.
    """
    result = []
    for name, meta in REGISTRY.items():
        if category and meta.category != category:
            continue
        result.append({
            "name": meta.name,
            "category": meta.category,
            "inputs": meta.inputs,
            "outputs": meta.outputs,
            "description": meta.description,
        })
    return result


def compute(factor_name: str, data: dict[str, pd.DataFrame]) -> pd.DataFrame:
    """Lazy compute a single factor.

    Args:
        factor_name: Registered factor name, e.g. "academic_carhart_mom".
        data: Dict mapping input field names to panel DataFrames.
              e.g. {"close": close_df, "volume": volume_df}

    Returns:
        DataFrame with factor output columns.

    Raises:
        ValueError: If factor not found or required inputs missing.
    """
    meta: FactorMeta | None = REGISTRY.get(factor_name)
    if meta is None:
        available = ", ".join(sorted(REGISTRY.keys()))
        raise ValueError(
            f"Factor '{factor_name}' not found in registry. "
            f"Available: {available}"
        )

    missing = set(meta.inputs) - set(data.keys())
    if missing:
        raise ValueError(
            f"Missing required inputs for '{factor_name}': {sorted(missing)}. "
            f"Required: {meta.inputs}"
        )

    kwargs = {inp: data[inp] for inp in meta.inputs}
    return meta.compute_fn(**kwargs)
