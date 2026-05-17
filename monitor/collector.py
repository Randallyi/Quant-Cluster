"""Data collection orchestrator for the monitor dashboard."""

from __future__ import annotations

import asyncio
import os
import re
import sqlite3
from typing import Callable

import httpx
from watchdog.events import FileSystemEventHandler
from watchdog.observers import Observer

from monitor.parser import parse_log_line
from monitor.state import StateCache


class DockerClient:
    """Async client for Docker Engine API via Unix socket."""

    SOCKET_PATH = "/var/run/docker.sock"
    BASE_URL = "http://localhost"
    AGENT_NAMES = {
        "hermes-hypothesis": "hypothesis",
        "hermes-data": "data_engineer",
        "hermes-quant": "quant_analyst",
        "hermes-risk": "risk_auditor",
        "hermes-writer": "strategy_writer",
        "quant-data-router": "data_router",
    }

    def __init__(self) -> None:
        transport = httpx.AsyncHTTPTransport(uds=self.SOCKET_PATH)
        self.client = httpx.AsyncClient(transport=transport, base_url=self.BASE_URL)

    async def _request(self, method: str, path: str) -> dict:
        """Make an HTTP request to the Docker socket and return JSON."""
        response = await self.client.request(method, path)
        response.raise_for_status()
        return response.json()

    async def list_quant_containers(self) -> list[dict]:
        """Query Docker for quant-cluster containers and map to agent state."""
        containers = await self._request("GET", "/containers/json")
        result: list[dict] = []
        for container in containers:
            names = container.get("Names", [])
            if not names:
                continue
            name = names[0].lstrip("/")
            if name not in self.AGENT_NAMES:
                continue
            status_str = container.get("Status", "")
            state = container.get("State", "")
            result.append(
                {
                    "agent": self.AGENT_NAMES[name],
                    "container_name": name,
                    "status": state,
                    "health": "healthy" if "healthy" in status_str.lower() else "unknown",
                    "uptime_sec": self._parse_uptime(status_str),
                }
            )
        return result

    def _parse_uptime(self, status: str) -> int:
        """Best-effort parsing of Docker Status uptime. Returns 0 if unparseable."""
        if not status.startswith("Up"):
            return 0

        # Strip health suffix, e.g. "Up 2 hours (healthy)"
        status = status.split("(")[0].strip()

        total = 0
        pattern = re.compile(r"(\d+)\s+(second|minute|hour|day|week)s?")
        for match in pattern.finditer(status):
            num = int(match.group(1))
            unit = match.group(2)
            if unit == "second":
                total += num
            elif unit == "minute":
                total += num * 60
            elif unit == "hour":
                total += num * 3600
            elif unit == "day":
                total += num * 86400
            elif unit == "week":
                total += num * 604800

        return total


class DBPoller:
    """SQLite read-only poller for orchestrator.db."""

    def __init__(self, db_path: str) -> None:
        self.db_path = db_path

    def _connect(self):
        return sqlite3.connect(f"file:{self.db_path}?mode=ro", uri=True)

    def get_runs(self, limit: int = 20) -> list[dict]:
        """Query pipeline_runs ordered by created_at DESC."""
        try:
            with self._connect() as conn:
                conn.row_factory = sqlite3.Row
                cur = conn.execute(
                    "SELECT run_id, topic, status, created_at, completed_at "
                    "FROM pipeline_runs ORDER BY created_at DESC LIMIT ?",
                    (limit,),
                )
                return [dict(row) for row in cur.fetchall()]
        except Exception:
            return []

    def get_run_status(self, run_id: str) -> dict:
        """Join pipeline_runs with agent_tasks for a specific run."""
        try:
            with self._connect() as conn:
                conn.row_factory = sqlite3.Row
                cur = conn.execute(
                    "SELECT * FROM pipeline_runs WHERE run_id = ?", (run_id,)
                )
                run = cur.fetchone()
                if not run:
                    return {}

                cur = conn.execute(
                    "SELECT agent_name, status, output_summary FROM agent_tasks WHERE run_id = ?",
                    (run_id,),
                )
                tasks = {
                    row["agent_name"]: {"status": row["status"], "summary": row["output_summary"]}
                    for row in cur.fetchall()
                }
                return {**dict(run), "tasks": tasks}
        except Exception:
            return {}

    def get_latest_active_run(self) -> dict | None:
        """Return the most recent run, or None if no runs exist."""
        try:
            with self._connect() as conn:
                conn.row_factory = sqlite3.Row
                cur = conn.execute(
                    "SELECT * FROM pipeline_runs ORDER BY created_at DESC LIMIT 1"
                )
                row = cur.fetchone()
                return dict(row) if row else None
        except Exception:
            return None


class AgentLogTailer:
    """Tail an agent.log file and emit parsed events via callback."""

    def __init__(self, log_path: str, callback: Callable[[dict], None]) -> None:
        self.log_path = os.path.abspath(log_path)
        self.callback = callback
        self._file = None
        self._observer = None

        if os.path.exists(self.log_path):
            self._file = open(self.log_path, "r", encoding="utf-8", errors="replace")
            self._file.seek(0, os.SEEK_END)

    def _read_new_lines(self) -> None:
        """Read from current offset to EOF and emit parsed events."""
        if self._file is None or self._file.closed:
            if os.path.exists(self.log_path):
                self._file = open(self.log_path, "r", encoding="utf-8", errors="replace")
                self._file.seek(0, os.SEEK_END)
            else:
                return

        for line in self._file:
            event = parse_log_line(line)
            self.callback(event)

    def start_watching(self) -> None:
        """Set up watchdog observer on the directory containing the log file."""
        if self._observer is not None:
            return

        class _Handler(FileSystemEventHandler):
            def __init__(self, tailer: AgentLogTailer) -> None:
                self.tailer = tailer

            def on_modified(self, event) -> None:
                if not event.is_directory and os.path.abspath(event.src_path) == self.tailer.log_path:
                    self.tailer._read_new_lines()

        directory = os.path.dirname(self.log_path)
        self._observer = Observer()
        self._observer.schedule(_Handler(self), directory, recursive=False)
        self._observer.start()

    def stop_watching(self) -> None:
        """Stop observer and close file handle."""
        if self._observer is not None:
            self._observer.stop()
            self._observer.join()
            self._observer = None
        if self._file is not None and not self._file.closed:
            self._file.close()
            self._file = None


class Collector:
    """Orchestrator that ties everything together and feeds StateCache."""

    AGENT_LOG_NAMES = {
        "hypothesis": "hypothesis",
        "data_engineer": "data",
        "quant_analyst": "quant",
        "risk_auditor": "risk",
        "strategy_writer": "writer",
    }

    def __init__(self, state: StateCache, db_path: str, agent_configs_path: str) -> None:
        self.state = state
        self.db = DBPoller(db_path)
        self.docker = DockerClient()
        self.agent_configs_path = agent_configs_path
        self.tailers: list[AgentLogTailer] = []
        self._poll_task: asyncio.Task | None = None

    def start(self) -> None:
        """Start log tailers for each agent and background polling loop."""
        for agent, log_name in self.AGENT_LOG_NAMES.items():
            log_path = os.path.join(
                self.agent_configs_path, agent, "logs", "agent.log"
            )
            if os.path.exists(log_path):
                tailer = AgentLogTailer(
                    log_path,
                    lambda event, agent=agent: self.state.append_log(agent, event),
                )
                tailer.start_watching()
                self.tailers.append(tailer)

        self._poll_task = asyncio.create_task(self._poll_loop())

    async def _poll_loop(self) -> None:
        """Poll DB and Docker every 2 seconds and update the cache."""
        while True:
            try:
                # 1. Poll DB
                runs = self.db.get_runs()
                self.state.set_runs(runs)
                latest = self.db.get_latest_active_run()
                if latest:
                    self.state.update_pipeline(latest)

                # 2. Poll Docker
                containers = await self.docker.list_quant_containers()
                for container in containers:
                    agent = container["agent"]
                    self.state.update_agent(
                        agent,
                        {
                            "status": container["status"],
                            "health": container["health"],
                            "uptime_sec": container["uptime_sec"],
                        },
                    )
            except Exception:
                # Keep the loop alive; errors are transient (socket/db unavailable)
                pass

            await asyncio.sleep(2)

    async def stop(self) -> None:
        """Cancel polling task, stop all tailers, close Docker client."""
        if self._poll_task is not None:
            self._poll_task.cancel()
            try:
                await self._poll_task
            except asyncio.CancelledError:
                pass
            self._poll_task = None

        for tailer in self.tailers:
            tailer.stop_watching()
        self.tailers.clear()

        await self.docker.client.aclose()
