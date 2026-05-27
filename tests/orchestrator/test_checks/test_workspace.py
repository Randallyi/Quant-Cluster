"""Tests for WorkspaceCheck."""
import pytest
from pathlib import Path

from orchestrator.checks.workspace import WorkspaceCheck


@pytest.mark.asyncio
async def test_workspace_passes_when_directories_exist(tmp_path: Path):
    """All expected dirs present → passed=True, no fix attempted."""
    expected = ["01_hypothesis", "02_data", "03_backtest", "04_risk", "05_strategy"]
    for d in expected:
        (tmp_path / d).mkdir()

    check = WorkspaceCheck(workspace_root=tmp_path)
    result = await check.run()

    assert result.passed is True
    assert result.fix_attempted is False
    assert result.name == "workspace"
    assert result.category == "workspace"
    assert result.severity == "fatal"


@pytest.mark.asyncio
async def test_workspace_creates_missing_directories(tmp_path: Path):
    """Some dirs missing → auto-creates them, passed=True."""
    # Only create 2 of the 5
    (tmp_path / "01_hypothesis").mkdir()
    (tmp_path / "03_backtest").mkdir()

    check = WorkspaceCheck(workspace_root=tmp_path)
    result = await check.run()

    assert result.passed is True
    assert result.fix_attempted is True
    assert result.fix_success is True

    # Verify all dirs now exist
    for d in check.EXPECTED_DIRS:
        assert (tmp_path / d).is_dir()
