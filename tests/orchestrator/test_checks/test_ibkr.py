"""Tests for IbkrGatewayCheck and DataRouterCheck."""
import asyncio
from unittest.mock import patch, AsyncMock, MagicMock

import aiohttp
import pytest

from orchestrator.checks.ibkr import IbkrGatewayCheck, DataRouterCheck


# ---------------------------------------------------------------------------
# IbkrGatewayCheck
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_ibkr_passes_when_tws_reachable():
    """socket.create_connection succeeds → passed=True."""
    mock_sock = MagicMock()

    with patch("socket.create_connection", return_value=mock_sock) as mock_conn:
        check = IbkrGatewayCheck()
        result = await check.run()

    mock_conn.assert_called_once_with(("localhost", 7497), timeout=5)
    mock_sock.close.assert_called_once()
    assert result.passed is True
    assert result.name == "ib_gateway"
    assert result.category == "external"
    assert result.severity == "fatal"
    assert "TWS port 7497 reachable" in result.message


@pytest.mark.asyncio
async def test_ibkr_fails_when_tws_unreachable():
    """socket.create_connection raises ConnectionRefusedError → passed=False."""
    with patch("socket.create_connection", side_effect=ConnectionRefusedError):
        check = IbkrGatewayCheck()
        result = await check.run()

    assert result.passed is False
    assert "Please start IB Gateway" in result.todo


# ---------------------------------------------------------------------------
# DataRouterCheck
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_data_router_passes_when_healthy():
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
        check = DataRouterCheck()
        result = await check.run()

    assert result.passed is True
    assert result.name == "data_router"
    assert result.category == "external"
    assert result.severity == "fatal"
    assert "Data Router healthy" in result.message


@pytest.mark.asyncio
async def test_data_router_fails_when_unhealthy():
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
        check = DataRouterCheck()
        result = await check.run()

    assert result.passed is False
    assert "Please check docker logs quant-data-router" in result.todo
