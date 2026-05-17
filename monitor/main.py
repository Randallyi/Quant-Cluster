"""FastAPI backend for the Quant Cluster Monitor dashboard."""

from __future__ import annotations

import asyncio
import os
from contextlib import asynccontextmanager
from datetime import datetime, timezone

from fastapi import FastAPI, Query, WebSocket, WebSocketDisconnect
from fastapi.responses import HTMLResponse
from fastapi.staticfiles import StaticFiles

from monitor.collector import Collector
from monitor.state import StateCache

DB_PATH = os.getenv("DB_PATH", "./orchestrator/orchestrator.db")
AGENT_CONFIGS_PATH = os.getenv("AGENT_CONFIGS_PATH", "./agent_configs")
WORKSPACE_PATH = os.getenv("WORKSPACE_PATH", "./shared_workspace")

state = StateCache()
collector: Collector | None = None
_broadcast_task: asyncio.Task | None = None

last_pipeline: dict = {}
last_agents: dict = {}


class ConnectionManager:
    """Manage active WebSocket connections."""

    def __init__(self) -> None:
        self._connections: set[WebSocket] = set()

    async def connect(self, ws: WebSocket) -> None:
        await ws.accept()
        self._connections.add(ws)

    def disconnect(self, ws: WebSocket) -> None:
        self._connections.discard(ws)

    async def broadcast(self, message: dict) -> None:
        dead: set[WebSocket] = set()
        for ws in self._connections:
            try:
                await ws.send_json(message)
            except Exception:
                dead.add(ws)
        for ws in dead:
            self._connections.discard(ws)


manager = ConnectionManager()


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


async def _broadcast_loop() -> None:
    heartbeat_counter = 0
    global last_pipeline, last_agents
    while True:
        try:
            await asyncio.sleep(1)
            heartbeat_counter += 1

            current_pipeline = state.get_pipeline()
            current_agents = state.get_all_agents()

            if current_pipeline != last_pipeline:
                last_pipeline = current_pipeline
                await manager.broadcast({"type": "pipeline", **current_pipeline})

            for agent_name, agent_data in current_agents.items():
                if agent_name not in last_agents or last_agents[agent_name] != agent_data:
                    last_agents[agent_name] = agent_data
                    await manager.broadcast(
                        {"type": "agent_task", "agent": agent_name, **agent_data}
                    )

            if heartbeat_counter >= 5:
                heartbeat_counter = 0
                await manager.broadcast({"type": "heartbeat", "timestamp": _now()})
        except asyncio.CancelledError:
            raise
        except Exception:
            pass


@asynccontextmanager
async def lifespan(app: FastAPI):
    global collector, _broadcast_task
    collector = Collector(state, DB_PATH, AGENT_CONFIGS_PATH)
    collector.start()
    _broadcast_task = asyncio.create_task(_broadcast_loop())
    yield
    if _broadcast_task:
        _broadcast_task.cancel()
        try:
            await _broadcast_task
        except asyncio.CancelledError:
            pass
    if collector:
        await collector.stop()


app = FastAPI(lifespan=lifespan)

INDEX_HTML = """<!DOCTYPE html>
<html lang="zh-CN">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>Quant Cluster Monitor</title>
<link rel="stylesheet" href="/static/style.css">
</head>
<body>
<div id="app"></div>
<script src="/static/app.js"></script>
</body>
</html>"""


@app.get("/", response_class=HTMLResponse)
async def root():
    return INDEX_HTML


@app.get("/api/status")
async def api_status():
    return {
        "pipeline": state.get_pipeline(),
        "agents": state.get_all_agents(),
        "runs": state.get_runs(),
    }


@app.get("/api/runs")
async def api_runs(limit: int = Query(default=20, ge=1)):
    runs = state.get_runs()
    return runs[:limit]


@app.get("/api/runs/{run_id}")
async def api_run_detail(run_id: str):
    if collector is None:
        return {}
    return collector.db.get_run_status(run_id)


@app.get("/api/agents")
async def api_agents():
    return state.get_all_agents()


@app.get("/api/agents/{agent}/logs")
async def api_agent_logs(agent: str, limit: int = Query(default=50, ge=1)):
    return state.get_logs(agent, limit=limit)


@app.websocket("/ws")
async def websocket_endpoint(ws: WebSocket):
    await manager.connect(ws)
    try:
        await ws.send_json(
            {
                "type": "init",
                "pipeline": state.get_pipeline(),
                "agents": state.get_all_agents(),
                "runs": state.get_runs(),
            }
        )
        while True:
            data = await ws.receive_json()
            if data.get("type") == "ping":
                await ws.send_json({"type": "pong"})
    except WebSocketDisconnect:
        manager.disconnect(ws)
    except Exception:
        manager.disconnect(ws)


static_path = os.path.join(os.path.dirname(__file__), "static")
if os.path.isdir(static_path):
    app.mount("/static", StaticFiles(directory=static_path), name="static")
