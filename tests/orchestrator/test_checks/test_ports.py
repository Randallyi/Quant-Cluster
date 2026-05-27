"""Tests for PortAvailabilityCheck."""
from unittest.mock import patch, AsyncMock

import pytest

from orchestrator.checks.ports import PortAvailabilityCheck


@pytest.mark.asyncio
async def test_ports_pass_when_all_free():
    """All ports free → passed=True, no fix attempted."""
    lsof_free = AsyncMock()
    lsof_free.communicate.return_value = (b"", b"")
    lsof_free.returncode = 1

    side_effects = [lsof_free] * len(PortAvailabilityCheck.EXPECTED_PORTS)

    with patch("asyncio.create_subprocess_exec", side_effect=side_effects):
        check = PortAvailabilityCheck()
        result = await check.run()

    assert result.passed is True
    assert result.fix_attempted is False
    assert result.fix_success is True
    assert result.name == "port_availability"
    assert result.category == "infra"
    assert result.severity == "fatal"
    assert "All expected ports are available" in result.message


@pytest.mark.asyncio
async def test_ports_kill_residual_process():
    """Residual process on port → kill → verify port free."""
    lsof_occ = AsyncMock()
    lsof_occ.communicate.return_value = (b"12345\n", b"")
    lsof_occ.returncode = 0

    lsof_free = AsyncMock()
    lsof_free.communicate.return_value = (b"", b"")
    lsof_free.returncode = 1

    ps_proc = AsyncMock()
    ps_proc.communicate.return_value = (b"python3 hermes-app\n", b"")
    ps_proc.returncode = 0

    side_effects = [
        lsof_occ,   # 8642 occupied
        ps_proc,    # docker check for 12345
        ps_proc,    # residual check for 12345
        lsof_free,  # 8642 re-check after kill
        lsof_free,  # 8643
        lsof_free,  # 8644
        lsof_free,  # 8645
        lsof_free,  # 8646
        lsof_free,  # 8888
        lsof_free,  # 10086
        lsof_free,  # 8080
    ]

    with (
        patch("asyncio.create_subprocess_exec", side_effect=side_effects),
        patch("os.kill") as mock_kill,
        patch("asyncio.sleep", return_value=None),
    ):
        check = PortAvailabilityCheck()
        result = await check.run()

    assert result.passed is True
    assert result.fix_attempted is True
    assert result.fix_success is True
    mock_kill.assert_called_once_with(12345, 9)


@pytest.mark.asyncio
async def test_ports_fails_on_external_process():
    """External process on port → passed=False, do NOT kill."""
    lsof_occ = AsyncMock()
    lsof_occ.communicate.return_value = (b"99999\n", b"")
    lsof_occ.returncode = 0

    lsof_free = AsyncMock()
    lsof_free.communicate.return_value = (b"", b"")
    lsof_free.returncode = 1

    ps_proc = AsyncMock()
    ps_proc.communicate.return_value = (b"nginx nginx: worker process\n", b"")
    ps_proc.returncode = 0

    side_effects = [
        lsof_occ,   # 8642 occupied
        ps_proc,    # docker check for 99999
        ps_proc,    # residual check for 99999
        ps_proc,    # external process info for 99999
        lsof_free,  # 8643
        lsof_free,  # 8644
        lsof_free,  # 8645
        lsof_free,  # 8646
        lsof_free,  # 8888
        lsof_free,  # 10086
        lsof_free,  # 8080
    ]

    with (
        patch("asyncio.create_subprocess_exec", side_effect=side_effects),
        patch("os.kill") as mock_kill,
    ):
        check = PortAvailabilityCheck()
        result = await check.run()

    assert result.passed is False
    assert result.fix_attempted is False
    assert result.fix_success is False
    assert "nginx" in result.message
    mock_kill.assert_not_called()
