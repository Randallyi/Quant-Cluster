"""Base abstractions for preflight checks."""
from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from typing import List, Dict, Optional


@dataclass
class CheckResult:
    name: str
    passed: bool
    category: str              # "infra" | "external" | "workspace"
    severity: str              # "fatal" | "warning"
    message: str
    fix_attempted: bool = False
    fix_success: bool = False
    todo: Optional[str] = None


class Check(ABC):
    name: str
    category: str
    auto_fixable: bool
    severity: str

    @abstractmethod
    async def run(self) -> CheckResult:
        ...
