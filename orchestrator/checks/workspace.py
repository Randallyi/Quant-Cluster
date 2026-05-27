"""Workspace directory permission check."""
from pathlib import Path
from typing import Optional

from orchestrator.checks.base import Check, CheckResult
from orchestrator.checks import register
from orchestrator.core.dag import WORKSPACE_ROOT


@register
class WorkspaceCheck(Check):
    name = "workspace"
    category = "workspace"
    auto_fixable = True
    severity = "fatal"
    EXPECTED_DIRS = ["01_hypothesis", "02_data", "03_backtest", "04_risk", "05_strategy"]

    def __init__(self, workspace_root: Optional[Path] = None):
        self.workspace_root = workspace_root or WORKSPACE_ROOT

    async def run(self) -> CheckResult:
        missing = [d for d in self.EXPECTED_DIRS if not (self.workspace_root / d).is_dir()]

        if not missing:
            return CheckResult(
                name=self.name,
                passed=True,
                category=self.category,
                severity=self.severity,
                message="All workspace directories present.",
            )

        # Attempt auto-fix: create missing directories
        fix_attempted = True
        fix_success = True
        created = []
        failed = []

        for d in missing:
            try:
                (self.workspace_root / d).mkdir(parents=True, exist_ok=True)
                created.append(d)
            except OSError:
                fix_success = False
                failed.append(d)

        if fix_success:
            message = f"Created missing workspace directories: {', '.join(created)}."
        else:
            message = f"Failed to create directories: {', '.join(failed)}."

        return CheckResult(
            name=self.name,
            passed=fix_success,
            category=self.category,
            severity=self.severity,
            message=message,
            fix_attempted=fix_attempted,
            fix_success=fix_success,
        )
