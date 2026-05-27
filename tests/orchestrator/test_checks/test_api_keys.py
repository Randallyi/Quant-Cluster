"""Tests for ApiKeysCheck."""
import os
from unittest.mock import patch, AsyncMock, MagicMock

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
    assert "所有 key 有效" in result.message


@pytest.mark.asyncio
async def test_api_keys_fails_when_missing():
    """Empty env → passed=False, message mentions missing keys."""
    with patch.dict(os.environ, {}, clear=True):
        check = ApiKeysCheck()
        result = await check.run()

    assert result.passed is False
    assert "ANTHROPIC_API_KEY" in result.message
    assert "TAVILY_API_KEY" in result.message
    assert "请在 .env 中配置" in result.todo
