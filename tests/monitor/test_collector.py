"""Unit tests for monitor.collector."""

import sqlite3
from unittest.mock import AsyncMock, Mock, patch

import pytest

from monitor.collector import AgentLogTailer, DBPoller, DockerClient


class TestAgentLogTailer:
    def test_reads_new_line_and_calls_callback(self, tmp_path):
        log_file = tmp_path / "agent.log"
        log_file.write_text("2026-05-17 09:02:56,504 INFO existing line\n")

        callback = Mock()
        tailer = AgentLogTailer(str(log_file), callback)

        # Append a new parseable line after the tailer has seeked to EOF
        with open(log_file, "a") as f:
            f.write(
                "2026-05-17 09:02:57,162 INFO tool write_file completed (0.65s, 115 chars)\n"
            )

        tailer._read_new_lines()

        assert callback.called
        event = callback.call_args[0][0]
        assert event["activity"] == "tool_call"
        assert event["tool"] == "write_file"
        assert event["duration_sec"] == 0.65
        assert event["output_chars"] == 115
        assert event["timestamp"] == "2026-05-17 09:02:57,162"

        tailer.stop_watching()


class TestDockerClient:
    @pytest.mark.asyncio
    async def test_list_quant_containers_filters_and_maps(self):
        client = DockerClient()

        sample_response = [
            {
                "Names": ["/hermes-hypothesis"],
                "Status": "Up 2 hours (healthy)",
                "State": "running",
            },
            {
                "Names": ["/some-other-container"],
                "Status": "Up 5 minutes",
                "State": "running",
            },
            {
                "Names": ["/hermes-quant"],
                "Status": "Up 3 days",
                "State": "running",
            },
        ]

        with patch.object(
            client, "_request", new_callable=AsyncMock
        ) as mock_request:
            mock_request.return_value = sample_response
            result = await client.list_quant_containers()

        assert len(result) == 2

        hypo = next(r for r in result if r["agent"] == "hypothesis")
        assert hypo["container_name"] == "hermes-hypothesis"
        assert hypo["status"] == "running"
        assert hypo["health"] == "healthy"
        assert hypo["uptime_sec"] == 7200

        quant = next(r for r in result if r["agent"] == "quant_analyst")
        assert quant["container_name"] == "hermes-quant"
        assert quant["status"] == "running"
        assert quant["health"] == "unknown"
        assert quant["uptime_sec"] == 259200

        await client.client.aclose()

    def test_parse_uptime(self):
        client = DockerClient()
        assert client._parse_uptime("Up 2 hours") == 7200
        assert client._parse_uptime("Up 5 minutes") == 300
        assert client._parse_uptime("Up 3 days") == 259200
        assert client._parse_uptime("Up 1 second") == 1
        assert client._parse_uptime("Up 2 hours (healthy)") == 7200
        assert client._parse_uptime("Up 1 week") == 604800
        assert client._parse_uptime("Exited (0) 2 hours ago") == 0
        assert client._parse_uptime("About an hour") == 0


class TestDBPoller:
    def test_nonexistent_db_returns_empty_list(self):
        poller = DBPoller("/nonexistent/path/to/orchestrator.db")
        assert poller.get_runs() == []

    def test_empty_db_returns_empty_list(self, tmp_path):
        db_path = tmp_path / "empty.db"
        sqlite3.connect(str(db_path)).close()
        poller = DBPoller(str(db_path))
        assert poller.get_runs() == []

    def test_get_run_status_nonexistent_run(self, tmp_path):
        db_path = tmp_path / "test.db"
        conn = sqlite3.connect(str(db_path))
        conn.executescript(
            """
            CREATE TABLE pipeline_runs (
                run_id TEXT PRIMARY KEY,
                topic TEXT,
                status TEXT,
                created_at TEXT
            );
            CREATE TABLE agent_tasks (
                task_id INTEGER PRIMARY KEY,
                run_id TEXT,
                agent_name TEXT,
                status TEXT
            );
            """
        )
        conn.close()
        poller = DBPoller(str(db_path))
        assert poller.get_run_status("nonexistent") == {}

    def test_get_runs_with_data(self, tmp_path):
        db_path = tmp_path / "test.db"
        conn = sqlite3.connect(str(db_path))
        conn.executescript(
            """
            CREATE TABLE pipeline_runs (
                run_id TEXT PRIMARY KEY,
                topic TEXT,
                status TEXT,
                created_at TEXT,
                completed_at TEXT
            );
            """
        )
        conn.execute(
            "INSERT INTO pipeline_runs (run_id, topic, status, created_at) VALUES (?, ?, ?, ?)",
            ("run_1", "topic_a", "completed", "2026-05-17T10:00:00"),
        )
        conn.execute(
            "INSERT INTO pipeline_runs (run_id, topic, status, created_at) VALUES (?, ?, ?, ?)",
            ("run_2", "topic_b", "running", "2026-05-17T11:00:00"),
        )
        conn.commit()
        conn.close()

        poller = DBPoller(str(db_path))
        runs = poller.get_runs()
        assert len(runs) == 2
        assert runs[0]["run_id"] == "run_2"
        assert runs[1]["run_id"] == "run_1"

    def test_get_run_status_with_tasks(self, tmp_path):
        db_path = tmp_path / "test.db"
        conn = sqlite3.connect(str(db_path))
        conn.executescript(
            """
            CREATE TABLE pipeline_runs (
                run_id TEXT PRIMARY KEY,
                topic TEXT,
                status TEXT,
                created_at TEXT,
                completed_at TEXT
            );
            CREATE TABLE agent_tasks (
                task_id INTEGER PRIMARY KEY,
                run_id TEXT,
                agent_name TEXT,
                status TEXT,
                output_summary TEXT
            );
            """
        )
        conn.execute(
            "INSERT INTO pipeline_runs (run_id, topic, status, created_at) VALUES (?, ?, ?, ?)",
            ("run_1", "topic_a", "running", "2026-05-17T10:00:00"),
        )
        conn.execute(
            "INSERT INTO agent_tasks (run_id, agent_name, status, output_summary) VALUES (?, ?, ?, ?)",
            ("run_1", "hypothesis", "completed", "done"),
        )
        conn.commit()
        conn.close()

        poller = DBPoller(str(db_path))
        status = poller.get_run_status("run_1")
        assert status["run_id"] == "run_1"
        assert status["tasks"]["hypothesis"]["status"] == "completed"
        assert status["tasks"]["hypothesis"]["summary"] == "done"

    def test_get_latest_active_run(self, tmp_path):
        db_path = tmp_path / "test.db"
        conn = sqlite3.connect(str(db_path))
        conn.executescript(
            """
            CREATE TABLE pipeline_runs (
                run_id TEXT PRIMARY KEY,
                topic TEXT,
                status TEXT,
                created_at TEXT,
                completed_at TEXT
            );
            """
        )
        conn.execute(
            "INSERT INTO pipeline_runs (run_id, topic, status, created_at) VALUES (?, ?, ?, ?)",
            ("run_1", "topic_a", "completed", "2026-05-17T10:00:00"),
        )
        conn.commit()
        conn.close()

        poller = DBPoller(str(db_path))
        latest = poller.get_latest_active_run()
        assert latest is not None
        assert latest["run_id"] == "run_1"
