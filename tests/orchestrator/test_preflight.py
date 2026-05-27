"""Tests for orchestrator.preflight module."""
import asyncio
import json
import sys
from io import StringIO
from unittest.mock import patch, MagicMock

import pytest

from orchestrator.checks import CHECK_REGISTRY
from orchestrator.checks.base import Check, CheckResult
from orchestrator.preflight import PreflightReport, PreflightRunner, main


class MockPassingCheck(Check):
    name = "mock_pass"
    category = "infra"
    auto_fixable = False
    severity = "fatal"

    async def run(self) -> CheckResult:
        return CheckResult(
            name=self.name,
            passed=True,
            category=self.category,
            severity=self.severity,
            message="Mock check passed.",
        )


class MockFailingCheck(Check):
    name = "mock_fail"
    category = "external"
    auto_fixable = False
    severity = "fatal"

    async def run(self) -> CheckResult:
        return CheckResult(
            name=self.name,
            passed=False,
            category=self.category,
            severity=self.severity,
            message="Mock check failed.",
            todo="Fix the mock check.",
        )


@pytest.mark.asyncio
async def test_runner_executes_all_checks():
    """Mock CHECK_REGISTRY with 1 mock check that passes."""
    mock_registry = {"mock_pass": MockPassingCheck}

    with patch("orchestrator.preflight.CHECK_REGISTRY", mock_registry):
        runner = PreflightRunner()
        report = await runner.run_all()

    assert len(report.checks) == 1
    assert report.checks[0].name == "mock_pass"
    assert report.all_passed is True


def test_report_shows_fatal_failures():
    """Manually construct PreflightReport with 1 pass + 1 fatal fail."""
    report = PreflightReport(
        checks=[
            CheckResult(
                name="pass_check",
                passed=True,
                category="infra",
                severity="fatal",
                message="All good.",
            ),
            CheckResult(
                name="fail_check",
                passed=False,
                category="external",
                severity="fatal",
                message="Something broke.",
                todo="Fix it.",
            ),
        ]
    )

    assert report.all_passed is False
    assert len(report.fatal_failed) == 1
    assert report.fatal_failed[0].name == "fail_check"

    data = report.to_dict()
    assert data["fatal_count"] == 1
    assert data["passed"] is False
    assert len(data["checks"]) == 2


@pytest.mark.asyncio
async def test_preflight_cli_json_output():
    """Mock PreflightRunner to return a passing report, verify JSON output."""
    report = PreflightReport(
        checks=[
            CheckResult(
                name="mock_pass",
                passed=True,
                category="infra",
                severity="fatal",
                message="Mock check passed.",
            ),
        ]
    )

    async def _mock_run_all():
        return report

    with patch("orchestrator.preflight.PreflightRunner") as MockRunner:
        MockRunner.return_value.run_all = _mock_run_all
        with patch("sys.stdout", new_callable=StringIO) as mock_stdout:
            with patch("sys.argv", ["preflight", "--json"]):
                with pytest.raises(SystemExit) as exc_info:
                    await main()
                assert exc_info.value.code == 0

            output = mock_stdout.getvalue()
            parsed = json.loads(output)
            assert parsed["passed"] is True


@pytest.mark.asyncio
async def test_preflight_runs_checks_in_correct_order():
    """Run PreflightRunner with real registry, verify all checks appear."""
    runner = PreflightRunner()
    report = await runner.run_all()

    assert len(report.checks) == len(CHECK_REGISTRY)

    # Verify ordering: fixable checks first, then non-fixable
    all_classes = list(CHECK_REGISTRY.values())
    fixable_names = {c().name for c in all_classes if c().auto_fixable}
    non_fixable_names = {c().name for c in all_classes if not c().auto_fixable}

    report_fixable_names = {c.name for c in report.checks if c.name in fixable_names}
    report_non_fixable_names = {c.name for c in report.checks if c.name in non_fixable_names}

    # All fixable checks should appear before any non-fixable check
    last_fixable_index = -1
    for i, c in enumerate(report.checks):
        if c.name in fixable_names:
            last_fixable_index = i

    first_non_fixable_index = len(report.checks)
    for i, c in enumerate(report.checks):
        if c.name in non_fixable_names:
            first_non_fixable_index = i
            break

    assert last_fixable_index < first_non_fixable_index
    assert report_fixable_names == fixable_names
    assert report_non_fixable_names == non_fixable_names
