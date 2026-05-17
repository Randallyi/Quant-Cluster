"""Integration tests for monitor.main."""

import asyncio
from unittest.mock import AsyncMock, patch

import pytest
from fastapi.testclient import TestClient

from monitor.main import app, state


@pytest.fixture(autouse=True)
def reset_state():
    state._pipeline = {}
    state._agents = {}
    state._runs = []
    state._logs = {}
    yield


@pytest.fixture
def client():
    with patch("monitor.main.Collector") as MockCollector, patch(
        "monitor.main._broadcast_loop", new=lambda: asyncio.sleep(3600)
    ):
        mock_instance = MockCollector.return_value
        mock_instance.stop = AsyncMock()
        mock_instance.db.get_run_status.return_value = {}
        with TestClient(app) as c:
            yield c


class TestEndpoints:
    def test_root_returns_html_with_title(self, client):
        response = client.get("/")
        assert response.status_code == 200
        assert "Quant Cluster Monitor" in response.text

    def test_api_status_returns_pipeline_and_agents(self, client):
        state.update_pipeline({"status": "running", "topic": "momentum"})
        state.update_agent("hypothesis", {"status": "idle"})
        response = client.get("/api/status")
        assert response.status_code == 200
        data = response.json()
        assert "pipeline" in data
        assert "agents" in data
        assert "runs" in data
        assert data["pipeline"]["status"] == "running"
        assert data["agents"]["hypothesis"]["status"] == "idle"

    def test_api_agents_returns_all_agents(self, client):
        state.update_agent("data_engineer", {"status": "busy"})
        response = client.get("/api/agents")
        assert response.status_code == 200
        assert response.json() == {"data_engineer": {"status": "busy"}}

    def test_api_agent_logs_returns_logs(self, client):
        state.append_log("hypothesis", {"msg": "hello", "activity": "log"})
        response = client.get("/api/agents/hypothesis/logs")
        assert response.status_code == 200
        logs = response.json()
        assert len(logs) == 1
        assert logs[0]["msg"] == "hello"


class TestWebSocket:
    def test_websocket_init_message(self, client):
        with client.websocket_connect("/ws") as ws:
            data = ws.receive_json()
            assert data["type"] == "init"
            assert "pipeline" in data
            assert "agents" in data
            assert "runs" in data

    def test_websocket_ping_pong(self, client):
        with client.websocket_connect("/ws") as ws:
            ws.receive_json()  # init
            ws.send_json({"type": "ping"})
            data = ws.receive_json()
            assert data == {"type": "pong"}

    def test_websocket_disconnect_cleanup(self, client):
        from monitor.main import manager

        initial_count = len(manager._connections)
        with client.websocket_connect("/ws") as ws:
            ws.receive_json()  # init
            assert len(manager._connections) == initial_count + 1
        assert len(manager._connections) == initial_count
