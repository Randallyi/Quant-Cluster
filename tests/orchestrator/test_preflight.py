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
    """Mock CHECK_REGISTRY with fixable and non-fixable checks, verify ordering."""

    class FixableCheck(Check):
        name = "fixable"
        category = "infra"
        auto_fixable = True
        severity = "fatal"

        async def run(self) -> CheckResult:
            return CheckResult(
                name=self.name,
                passed=True,
                category=self.category,
                severity=self.severity,
                message="Fixable ok.",
            )

    class NonFixableCheck(Check):
        name = "non_fixable"
        category = "external"
        auto_fixable = False
        severity = "fatal"

        async def run(self) -> CheckResult:
            return CheckResult(
                name=self.name,
                passed=True,
                category=self.category,
                severity=self.severity,
                message="Non-fixable ok.",
            )

    mock_registry = {"fixable": FixableCheck, "non_fixable": NonFixableCheck}
    with patch("orchestrator.preflight.CHECK_REGISTRY", mock_registry):
        runner = PreflightRunner()
        report = await runner.run_all()

    names = [c.name for c in report.checks]
    assert names.index("fixable") < names.index("non_fixable")
    assert len(report.checks) == len(mock_registry)


@pytest.mark.asyncio
async def test_runner_retries_fixable_checks():
    """Mock a fixable check that attempts a fix then passes on retry."""

    class MockRetryCheck(Check):
        name = "mock_retry"
        category = "infra"
        auto_fixable = True
        severity = "fatal"
        _call_count = 0

        async def run(self) -> CheckResult:
            MockRetryCheck._call_count += 1
            if MockRetryCheck._call_count == 1:
                return CheckResult(
                    name=self.name,
                    passed=False,
                    category=self.category,
                    severity=self.severity,
                    message="Attempting fix.",
                    fix_attempted=True,
                )
            return CheckResult(
                name=self.name,
                passed=True,
                category=self.category,
                severity=self.severity,
                message="Fixed on retry.",
            )

    mock_registry = {"mock_retry": MockRetryCheck}
    with patch("orchestrator.preflight.CHECK_REGISTRY", mock_registry):
        runner = PreflightRunner()
        report = await runner.run_all()

    assert MockRetryCheck._call_count == 2
    assert report.checks[0].passed is True
    assert report.checks[0].message == "Fixed on retry."


@pytest.mark.asyncio
async def test_runner_warning_does_not_block():
    """A warning-level failure should not set all_passed to False."""

    class MockWarningCheck(Check):
        name = "mock_warning"
        category = "external"
        auto_fixable = False
        severity = "warning"

        async def run(self) -> CheckResult:
            return CheckResult(
                name=self.name,
                passed=False,
                category=self.category,
                severity=self.severity,
                message="Warning: something.",
            )

    mock_registry = {"mock_warning": MockWarningCheck}
    with patch("orchestrator.preflight.CHECK_REGISTRY", mock_registry):
        runner = PreflightRunner()
        report = await runner.run_all()

    assert report.all_passed is True
    assert len(report.checks) == 1
    assert report.checks[0].severity == "warning"


@pytest.mark.asyncio
async def test_runner_catches_check_exceptions():
    """A check that raises should not crash the runner."""

    class MockCrashCheck(Check):
        name = "mock_crash"
        category = "infra"
        auto_fixable = False
        severity = "fatal"

        async def run(self) -> CheckResult:
            raise RuntimeError("boom")

    mock_registry = {"mock_crash": MockCrashCheck}
    with patch("orchestrator.preflight.CHECK_REGISTRY", mock_registry):
        runner = PreflightRunner()
        report = await runner.run_all()

    assert len(report.checks) == 1
    assert report.checks[0].passed is False
    assert report.checks[0].name == "mock_crash"
    assert "Check crashed: boom" in report.checks[0].message
    assert report.checks[0].todo == "Please investigate mock_crash check"


@pytest.mark.asyncio
async def test_cli_launch_mode_outputs_failures():
    """Invoke CLI with --mode=launch and a failing report, verify output and exit code."""
    report = PreflightReport(
        checks=[
            CheckResult(
                name="mock_fail",
                passed=False,
                category="external",
                severity="fatal",
                message="Mock check failed.",
                todo="Fix the mock check.",
            ),
        ]
    )

    async def _mock_run_all():
        return report

    with patch("orchestrator.preflight.PreflightRunner") as MockRunner:
        MockRunner.return_value.run_all = _mock_run_all
        with patch("sys.stdout", new_callable=StringIO) as mock_stdout:
            with patch("sys.argv", ["preflight", "--mode=launch"]):
                with pytest.raises(SystemExit) as exc_info:
                    await main()
                assert exc_info.value.code == 1

            output = mock_stdout.getvalue()
            assert "🔴 [mock_fail] Fix the mock check." in output


@pytest.mark.asyncio
async def test_pipeline_blocked_when_preflight_fails():
    """Pipeline should be blocked if preflight report has fatal failures."""
    from orchestrator.core.orchestrator import InteractiveOrchestrator
    from orchestrator.preflight import PreflightReport
    from orchestrator.checks.base import CheckResult

    report = PreflightReport(
        checks=[
            CheckResult(
                name="mock_fail",
                passed=False,
                category="external",
                severity="fatal",
                message="Mock check failed.",
                todo="Fix the mock check.",
            ),
        ]
    )

    async def _mock_run_all():
        return report

    with patch("orchestrator.core.orchestrator.PreflightRunner") as MockRunner:
        MockRunner.return_value.run_all = _mock_run_all
        orch = InteractiveOrchestrator()
        result = await orch.run_pipeline(topic="test", skip_preflight=False)

    assert result["status"] == "failed"
    assert result["reason"] == "preflight_failed"


@pytest.mark.asyncio
async def test_pipeline_skips_preflight_when_flag_set():
    """Preflight should be skipped when skip_preflight=True."""
    from orchestrator.core.orchestrator import InteractiveOrchestrator

    with patch("orchestrator.core.orchestrator.PreflightRunner") as MockRunner:
        mock_run_all = MagicMock()
        MockRunner.return_value.run_all = mock_run_all
        orch = InteractiveOrchestrator()
        result = await orch.run_pipeline(topic="test", skip_preflight=True, dry_run=True)

    mock_run_all.assert_not_called()
