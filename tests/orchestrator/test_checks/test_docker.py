"""Tests for DockerContainersCheck."""
import asyncio
from unittest.mock import patch, AsyncMock

import pytest

from orchestrator.checks.docker import DockerContainersCheck


@pytest.mark.asyncio
async def test_docker_passes_when_all_containers_running():
    """All 6 containers running → passed=True, no fix attempted."""
    mock_proc = AsyncMock()
    mock_proc.communicate.return_value = (
        b"quant-data-router\nhermes-hypothesis\nhermes-data\n"
        b"hermes-quant\nhermes-risk\nhermes-writer\n",
        b"",
    )
    mock_proc.returncode = 0

    with patch("asyncio.create_subprocess_exec", return_value=mock_proc):
        check = DockerContainersCheck()
        result = await check.run()

    assert result.passed is True
    assert result.fix_attempted is False
    assert result.name == "docker_containers"
    assert result.category == "infra"
    assert result.severity == "fatal"


@pytest.mark.asyncio
async def test_docker_attempts_restart_on_missing():
    """Missing one container → auto-restart → verify all present."""
    # First call: missing quant-data-router
    first_proc = AsyncMock()
    first_proc.communicate.return_value = (
        b"hermes-hypothesis\nhermes-data\nhermes-quant\n"
        b"hermes-risk\nhermes-writer\n",
        b"",
    )
    first_proc.returncode = 0

    # docker compose up -d quant-data-router succeeds
    compose_proc = AsyncMock()
    compose_proc.communicate.return_value = (b"", b"")
    compose_proc.returncode = 0

    # Second call: all containers now present
    second_proc = AsyncMock()
    second_proc.communicate.return_value = (
        b"quant-data-router\nhermes-hypothesis\nhermes-data\n"
        b"hermes-quant\nhermes-risk\nhermes-writer\n",
        b"",
    )
    second_proc.returncode = 0

    side_effects = [first_proc, compose_proc, second_proc]

    with patch("asyncio.create_subprocess_exec", side_effect=side_effects):
        check = DockerContainersCheck()
        result = await check.run()

    assert result.passed is True
    assert result.fix_attempted is True
    assert result.fix_success is True


@pytest.mark.asyncio
async def test_docker_fails_when_docker_not_installed():
    """Docker binary missing → passed=False, fix attempted but fails."""
    with patch("asyncio.create_subprocess_exec", side_effect=FileNotFoundError):
        check = DockerContainersCheck()
        result = await check.run()

    assert result.passed is False
    assert result.fix_attempted is True
    assert result.fix_success is False


@pytest.mark.asyncio
async def test_docker_fails_when_docker_ps_returns_error():
    """docker ps exits with error → passed=False."""
    ps_proc = AsyncMock()
    ps_proc.communicate.return_value = (b"", b"error")
    ps_proc.returncode = 1

    compose_proc = AsyncMock()
    compose_proc.communicate.return_value = (b"", b"")
    compose_proc.returncode = 0

    side_effects = [ps_proc, compose_proc, ps_proc]

    with patch("asyncio.create_subprocess_exec", side_effect=side_effects):
        check = DockerContainersCheck()
        result = await check.run()

    assert result.passed is False


@pytest.mark.asyncio
async def test_docker_fails_when_compose_up_fails():
    """Missing containers and docker compose up -d fails → passed=False."""
    ps_proc = AsyncMock()
    ps_proc.communicate.return_value = (b"", b"")
    ps_proc.returncode = 0

    compose_proc = AsyncMock()
    compose_proc.communicate.return_value = (b"", b"error")
    compose_proc.returncode = 1

    side_effects = [ps_proc, compose_proc]

    with patch("asyncio.create_subprocess_exec", side_effect=side_effects):
        check = DockerContainersCheck()
        result = await check.run()

    assert result.passed is False
    assert result.fix_attempted is True
    assert result.fix_success is False
