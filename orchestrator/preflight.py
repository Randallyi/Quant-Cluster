"""Preflight runner: orchestrates all checks in 3 phases and produces reports."""
import argparse
import json
import sys
from dataclasses import dataclass, field, asdict

from rich.console import Console
from rich.table import Table

from orchestrator.checks import CHECK_REGISTRY
from orchestrator.checks.base import CheckResult


@dataclass
class PreflightReport:
    checks: list[CheckResult] = field(default_factory=list)

    @property
    def all_passed(self) -> bool:
        return all(c.passed or c.severity == "warning" for c in self.checks)

    @property
    def fatal_failed(self) -> list[CheckResult]:
        return [c for c in self.checks if not c.passed and c.severity == "fatal"]

    def print_table(self) -> None:
        console = Console()
        console.print("\n🔍 Quant Cluster Preflight Report\n")

        table = Table(show_header=True, header_style="bold magenta")
        table.add_column("Check", style="dim", width=20)
        table.add_column("Status", width=10)
        table.add_column("Category", width=12)
        table.add_column("Message / Action", width=45)

        for check in self.checks:
            if check.passed:
                status = "✅ PASS"
                status_style = "green"
            elif check.severity == "warning":
                status = "⚠️ WARN"
                status_style = "yellow"
            else:
                status = "🔴 FAIL"
                status_style = "red"

            table.add_row(
                check.name,
                f"[{status_style}]{status}[/{status_style}]",
                check.category,
                check.message,
            )

        console.print(table)

        if self.all_passed:
            console.print("\n🟢 All checks passed. Ready to launch.\n")
        else:
            fatal_count = len(self.fatal_failed)
            console.print(f"\n🔴 {fatal_count} fatal failure(s) detected. Pipeline blocked.\n")
            console.print("💡 Todo list:")
            for i, c in enumerate(self.fatal_failed, 1):
                console.print(f"  {i}. [{c.name}] {c.todo}")
            console.print()

    def to_dict(self) -> dict:
        return {
            "passed": self.all_passed,
            "fatal_count": len(self.fatal_failed),
            "checks": [asdict(c) for c in self.checks],
        }


class PreflightRunner:
    async def run_all(self) -> PreflightReport:
        report = PreflightReport()
        all_classes = list(CHECK_REGISTRY.values())

        # Phase 1: auto-fixable checks
        fixable = [c for c in all_classes if c.auto_fixable]
        for check_cls in fixable:
            try:
                result = await check_cls().run()
            except Exception as exc:
                result = CheckResult(
                    name=check_cls.name,
                    passed=False,
                    category=check_cls.category,
                    severity=check_cls.severity,
                    message=f"Check crashed: {exc}",
                    todo=f"Please investigate {check_cls.name} check",
                )
            report.checks.append(result)

        # Phase 2: re-verify anything that was fixed
        for i, result in enumerate(list(report.checks)):
            if result.fix_attempted:
                check_cls = CHECK_REGISTRY.get(result.name)
                if check_cls is None:
                    continue
                try:
                    retry = await check_cls().run()
                except Exception as exc:
                    retry = CheckResult(
                        name=check_cls.name,
                        passed=False,
                        category=check_cls.category,
                        severity=check_cls.severity,
                        message=f"Check crashed: {exc}",
                        todo=f"Please investigate {check_cls.name} check",
                    )
                report.checks[i] = retry

        # Phase 3: non-fixable checks
        non_fixable = [c for c in all_classes if not c.auto_fixable]
        for check_cls in non_fixable:
            try:
                result = await check_cls().run()
            except Exception as exc:
                result = CheckResult(
                    name=check_cls.name,
                    passed=False,
                    category=check_cls.category,
                    severity=check_cls.severity,
                    message=f"Check crashed: {exc}",
                    todo=f"Please investigate {check_cls.name} check",
                )
            report.checks.append(result)

        return report


async def main():
    parser = argparse.ArgumentParser(description="Quant Cluster Preflight Checks")
    parser.add_argument("--json", action="store_true", help="Output JSON instead of table")
    parser.add_argument("--mode", choices=["interactive", "launch"], default="interactive")
    args = parser.parse_args()

    runner = PreflightRunner()
    report = await runner.run_all()

    if args.json:
        print(json.dumps(report.to_dict(), indent=2, ensure_ascii=False))
    elif args.mode == "launch":
        if report.all_passed:
            print("🟢 Preflight passed")
        else:
            for c in report.fatal_failed:
                print(f"🔴 [{c.name}] {c.todo}")
    else:
        report.print_table()

    sys.exit(0 if report.all_passed else 1)


if __name__ == "__main__":
    import asyncio
    asyncio.run(main())
