"""Preflight check registry — auto-imports all check modules."""
import pkgutil
from typing import Dict

from orchestrator.checks.base import Check, CheckResult

CHECK_REGISTRY: Dict[str, type[Check]] = {}


def register(cls: type[Check]) -> type[Check]:
    CHECK_REGISTRY[cls.name] = cls
    return cls


# Auto-import all submodules to trigger @register decorators
import sys

for _, _modname, _ in pkgutil.iter_modules(__path__):
    try:
        __import__(f"{__package__}.{_modname}")
    except ImportError as exc:
        print(f"Warning: could not import check module {_modname!r}: {exc}", file=sys.stderr)
