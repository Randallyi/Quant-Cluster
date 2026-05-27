from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass

__all__ = ["FactorMeta", "factor", "REGISTRY", "unregister"]

@dataclass
class FactorMeta:
    name: str
    category: str
    inputs: list[str]
    outputs: list[str]
    description: str
    compute_fn: Callable

REGISTRY: dict[str, FactorMeta] = {}

def factor(name, category, inputs, outputs, description=""):
    def decorator(fn):
        meta = FactorMeta(name=name, category=category, inputs=inputs,
                          outputs=outputs, description=description, compute_fn=fn)
        REGISTRY[name] = meta
        return fn
    return decorator

def unregister(name):
    REGISTRY.pop(name, None)
