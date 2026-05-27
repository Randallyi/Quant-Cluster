"""Adapt Vibe-Trading zoo modules to @factor registry.

Scans factors/zoo/ directories, imports each alpha module,
reads __alpha_meta__, and registers a @factor-wrapped compute.
"""

from __future__ import annotations

import importlib
import logging
from pathlib import Path

import pandas as pd

from factors.core.meta import FactorMeta, REGISTRY

logger = logging.getLogger(__name__)


def _register_zoo_module(module_name: str, category: str) -> None:
    """Import a zoo module and register its compute function."""
    try:
        mod = importlib.import_module(module_name)
    except Exception as exc:
        logger.warning("Failed to import %s: %s", module_name, exc)
        return

    if not hasattr(mod, "__alpha_meta__") or not hasattr(mod, "compute"):
        return

    meta = mod.__alpha_meta__
    compute_fn = mod.compute
    alpha_id = meta["id"]
    columns_required = meta.get("columns_required", [])
    nickname = meta.get("nickname", alpha_id)

    # Wrap compute — registry passes kwargs per field; assemble into panel dict
    def _wrapped_compute(**kwargs) -> pd.DataFrame:
        return compute_fn(kwargs)

    REGISTRY[alpha_id] = FactorMeta(
        name=alpha_id,
        category=category,
        inputs=columns_required,
        outputs=[alpha_id],
        description=nickname,
        compute_fn=_wrapped_compute,
    )


def register_all_zoos() -> None:
    """Scan and register all zoo modules."""
    zoo_root = Path(__file__).parent / "zoo"
    if not zoo_root.exists():
        return

    for zoo_dir in sorted(zoo_root.iterdir()):
        if not zoo_dir.is_dir() or zoo_dir.name.startswith("_"):
            continue
        category = zoo_dir.name
        init_file = zoo_dir / "__init__.py"
        if not init_file.exists():
            continue

        for py_file in sorted(zoo_dir.glob("*.py")):
            if py_file.name.startswith("_"):
                continue
            module_name = f"factors.zoo.{category}.{py_file.stem}"
            _register_zoo_module(module_name, category)
