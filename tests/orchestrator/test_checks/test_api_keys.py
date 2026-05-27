"""Tests for ApiKeysCheck."""
import asyncio
import os
from unittest.mock import patch, AsyncMock, MagicMock

import aiohttp
import pytest

from orchestrator.checks.api_keys import ApiKeysCheck


@pytest.mark.asyncio
async def test_api_keys_pass_when_env_present_and_valid():
    """Both keys present and Kimi API returns 200 → passed=True."""
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

    with (
        patch.dict(os.environ, {"ANTHROPIC_API_KEY": "test-key", "TAVILY_API_KEY": "test-key2"}),
        patch("aiohttp.ClientSession", return_value=mock_client_session),
    ):
        check = ApiKeysCheck()
        result = await check.run()

    assert result.passed is True
    assert result.name == "api_keys"
    assert result.category == "infra"
    assert result.severity == "fatal"
    assert "All API keys are valid." in result.message


@pytest.mark.asyncio
async def test_api_keys_fails_when_missing():
    """Empty env → passed=False, message mentions missing keys."""
    with patch.dict(os.environ, {}, clear=True):
        check = ApiKeysCheck()
        result = await check.run()

    assert result.passed is False
    assert "ANTHROPIC_API_KEY" in result.message
    assert "TAVILY_API_KEY" in result.message
    assert "Please configure in .env" in result.todo


@pytest.mark.asyncio
async def test_api_keys_fails_on_api_non_200():
    """Mock Kimi API returns 401 → passed=False."""
    mock_response = AsyncMock()
    mock_response.status = 401

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

    with (
        patch.dict(os.environ, {"ANTHROPIC_API_KEY": "test-key", "TAVILY_API_KEY": "test-key2"}),
        patch("aiohttp.ClientSession", return_value=mock_client_session),
    ):
        check = ApiKeysCheck()
        result = await check.run()

    assert result.passed is False
    assert "401" in result.message


@pytest.mark.asyncio
async def test_api_keys_fails_on_client_error():
    """Mock session.get raises aiohttp.ClientError → passed=False."""
    mock_session = AsyncMock()
    mock_session.__aenter__ = AsyncMock(return_value=mock_session)
    mock_session.__aexit__ = AsyncMock(return_value=None)
    mock_session.get = MagicMock(side_effect=aiohttp.ClientError("connection failed"))

    mock_client_session = AsyncMock()
    mock_client_session.__aenter__ = AsyncMock(return_value=mock_session)
    mock_client_session.__aexit__ = AsyncMock(return_value=None)

    with (
        patch.dict(os.environ, {"ANTHROPIC_API_KEY": "test-key", "TAVILY_API_KEY": "test-key2"}),
        patch("aiohttp.ClientSession", return_value=mock_client_session),
    ):
        check = ApiKeysCheck()
        result = await check.run()

    assert result.passed is False
    assert "connection failed" in result.message


@pytest.mark.asyncio
async def test_api_keys_fails_on_timeout():
    """Mock session.get raises asyncio.TimeoutError → passed=False."""
    mock_session = AsyncMock()
    mock_session.__aenter__ = AsyncMock(return_value=mock_session)
    mock_session.__aexit__ = AsyncMock(return_value=None)
    mock_session.get = MagicMock(side_effect=asyncio.TimeoutError())

    mock_client_session = AsyncMock()
    mock_client_session.__aenter__ = AsyncMock(return_value=mock_session)
    mock_client_session.__aexit__ = AsyncMock(return_value=None)

    with (
        patch.dict(os.environ, {"ANTHROPIC_API_KEY": "test-key", "TAVILY_API_KEY": "test-key2"}),
        patch("aiohttp.ClientSession", return_value=mock_client_session),
    ):
        check = ApiKeysCheck()
        result = await check.run()

    assert result.passed is False
