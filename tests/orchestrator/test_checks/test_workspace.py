"""Tests for WorkspaceCheck."""
import pytest
from pathlib import Path

from orchestrator.checks.workspace import WorkspaceCheck


@pytest.mark.asyncio
async def test_workspace_passes_when_directories_exist(tmp_path: Path):
    """All expected dirs present → passed=True, no fix attempted."""
    for d in WorkspaceCheck.EXPECTED_DIRS:
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


@pytest.mark.asyncio
async def test_workspace_fails_when_mkdir_raises_oserror(tmp_path: Path, monkeypatch):
    """OSError during mkdir → passed=False, fix_attempted=True, fix_success=False."""
    def mock_mkdir(*args, **kwargs):
        raise PermissionError(13, "Permission denied")

    monkeypatch.setattr(Path, "mkdir", mock_mkdir)

    check = WorkspaceCheck(workspace_root=tmp_path)
    result = await check.run()

    assert result.passed is False
    assert result.fix_attempted is True
    assert result.fix_success is False
