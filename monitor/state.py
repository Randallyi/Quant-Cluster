"""Thread-safe in-memory state cache for the monitor dashboard."""

import threading
from typing import Any


class StateCache:
    """Thread-safe in-memory cache for pipeline, agent, run and log state."""

    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._pipeline: dict[str, Any] = {}
        self._agents: dict[str, dict[str, Any]] = {}
        self._runs: list[dict[str, Any]] = []
        self._logs: dict[str, list[dict[str, Any]]] = {}

    # -- pipeline ----------------------------------------------------------

    def update_pipeline(self, data: dict) -> None:
        """Merge *data* into the shared pipeline state."""
        with self._lock:
            self._pipeline.update(dict(data))

    def get_pipeline(self) -> dict:
        """Return a shallow copy of the pipeline state."""
        with self._lock:
            return dict(self._pipeline)

    # -- agents ------------------------------------------------------------

    def update_agent(self, agent: str, data: dict) -> None:
        """Merge *data* into the state for *agent*."""
        with self._lock:
            if agent not in self._agents:
                self._agents[agent] = {}
            self._agents[agent].update(dict(data))

    def get_agent(self, agent: str) -> dict:
        """Return a shallow copy of the state for *agent*, or {}."""
        with self._lock:
            return dict(self._agents.get(agent, {}))

    def get_all_agents(self) -> dict:
        """Return a shallow copy of all agent states."""
        with self._lock:
            return {k: dict(v) for k, v in self._agents.items()}

    # -- runs --------------------------------------------------------------

    def set_runs(self, runs: list) -> None:
        """Replace the run history with *runs*."""
        with self._lock:
            self._runs = [dict(r) for r in runs]

    def get_runs(self) -> list:
        """Return a copy of the run history."""
        with self._lock:
            return [dict(r) for r in self._runs]

    # -- logs --------------------------------------------------------------

    def append_log(self, agent: str, event: dict, max_keep: int = 200) -> None:
        """Append *event* to *agent*'s log and trim to *max_keep*."""
        with self._lock:
            if agent not in self._logs:
                self._logs[agent] = []
            self._logs[agent].append(dict(event))
            if len(self._logs[agent]) > max_keep:
                self._logs[agent] = self._logs[agent][-max_keep:]

    def get_logs(self, agent: str, limit: int = 50) -> list:
        """Return the last *limit* log events for *agent*."""
        with self._lock:
            return [dict(e) for e in self._logs.get(agent, [])[-limit:]]

    def get_all_logs(self, limit: int = 50) -> dict:
        """Return the last *limit* log events for every agent."""
        with self._lock:
            return {k: [dict(e) for e in v[-limit:]] for k, v in self._logs.items()}
