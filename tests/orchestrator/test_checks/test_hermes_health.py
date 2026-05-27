"""Tests for HermesHealthCheck."""
import asyncio
from unittest.mock import patch, AsyncMock, MagicMock

import aiohttp
import pytest

from orchestrator.checks.hermes_health import HermesHealthCheck


@pytest.mark.asyncio
async def test_hermes_passes_when_all_respond():
    """All 5 health checks return 200 → passed=True, '5/5' in message."""
    mock_response = AsyncMock()
    mock_response.status = 200

    mock_get_cm = AsyncMock()
    mock_get_cm.__aenter__ = AsyncMock(return_value=mock_response)
    mock_get_cm.__aexit__ = AsyncMock(return_value=None)

    mock_session = AsyncMock()
    mock_session.__aenter__ = AsyncMock(return_value=mock_session)
    mock_session.__aexit__ = AsyncMock(return_value=None)
    mock_session.get = MagicMock(return_value=mock_get_cm)

    mock_client_session = AsyncMock()
    mock_client_session.__aenter__ = AsyncMock(return_value=mock_session)
    mock_client_session.__aexit__ = AsyncMock(return_value=None)

    with patch("aiohttp.ClientSession", return_value=mock_client_session):
        check = HermesHealthCheck()
        result = await check.run()

    assert result.passed is True
    assert "5/5" in result.message
    assert result.name == "hermes_health"
    assert result.category == "infra"
    assert result.severity == "fatal"


@pytest.mark.asyncio
async def test_hermes_fails_when_some_offline():
    """First agent returns 503, rest 200 → passed=False, failed agent in todo."""
    ok_response = AsyncMock()
    ok_response.status = 200

    fail_response = AsyncMock()
    fail_response.status = 503

    # Side effect: first call returns 503, rest return 200
    side_effects = [fail_response, ok_response, ok_response, ok_response, ok_response]

    mock_get_cms = []
    for resp in side_effects:
        mock_get_cm = AsyncMock()
        mock_get_cm.__aenter__ = AsyncMock(return_value=resp)
        mock_get_cm.__aexit__ = AsyncMock(return_value=None)
        mock_get_cms.append(mock_get_cm)

    mock_session = AsyncMock()
    mock_session.__aenter__ = AsyncMock(return_value=mock_session)
    mock_session.__aexit__ = AsyncMock(return_value=None)
    mock_session.get = MagicMock(side_effect=mock_get_cms)

    mock_client_session = AsyncMock()
    mock_client_session.__aenter__ = AsyncMock(return_value=mock_session)
    mock_client_session.__aexit__ = AsyncMock(return_value=None)

    with patch("aiohttp.ClientSession", return_value=mock_client_session):
        check = HermesHealthCheck()
        result = await check.run()

    assert result.passed is False
    assert "hypothesis" in result.todo
    assert "Please check Docker container status" in result.todo


@pytest.mark.asyncio
async def test_hermes_fails_on_connection_error():
    """Mock session.get raises aiohttp.ClientError → passed=False."""
    mock_session = AsyncMock()
    mock_session.__aenter__ = AsyncMock(return_value=mock_session)
    mock_session.__aexit__ = AsyncMock(return_value=None)
    mock_session.get = MagicMock(side_effect=aiohttp.ClientError("connection refused"))

    mock_client_session = AsyncMock()
    mock_client_session.__aenter__ = AsyncMock(return_value=mock_session)
    mock_client_session.__aexit__ = AsyncMock(return_value=None)

    with patch("aiohttp.ClientSession", return_value=mock_client_session):
        check = HermesHealthCheck()
        result = await check.run()

    assert result.passed is False
    assert "hypothesis" in result.message


@pytest.mark.asyncio
async def test_hermes_fails_on_timeout():
    """Mock session.get raises asyncio.TimeoutError → passed=False."""
    mock_session = AsyncMock()
    mock_session.__aenter__ = AsyncMock(return_value=mock_session)
    mock_session.__aexit__ = AsyncMock(return_value=None)
    mock_session.get = MagicMock(side_effect=asyncio.TimeoutError())

    mock_client_session = AsyncMock()
    mock_client_session.__aenter__ = AsyncMock(return_value=mock_session)
    mock_client_session.__aexit__ = AsyncMock(return_value=None)

    with patch("aiohttp.ClientSession", return_value=mock_client_session):
        check = HermesHealthCheck()
        result = await check.run()

    assert result.passed is False
    assert "hypothesis" in result.message
