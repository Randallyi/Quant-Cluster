"""Tests for WebBridgeCheck."""
from unittest.mock import patch, AsyncMock, MagicMock

import pytest

from orchestrator.checks.webbridge import WebBridgeCheck


@pytest.mark.asyncio
async def test_webbridge_passes_when_healthy():
    """HTTP 200 → passed=True."""
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
        check = WebBridgeCheck()
        result = await check.run()

    assert result.passed is True
    assert result.name == "webbridge"
    assert result.category == "external"
    assert result.severity == "fatal"
    assert "WebBridge responding" in result.message


@pytest.mark.asyncio
async def test_webbridge_fails_when_unhealthy():
    """HTTP 500 → passed=False."""
    mock_response = AsyncMock()
    mock_response.status = 500

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
        check = WebBridgeCheck()
        result = await check.run()

    assert result.passed is False
    assert "Please start WebBridge: python3 -m webbridge.server" in result.todo
