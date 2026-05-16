"""SQLite state machine for pipeline runs and agent tasks."""
import sqlite3
from pathlib import Path
from datetime import datetime
from typing import Dict, List, Optional

DEFAULT_DB_PATH = Path(__file__).parent.parent / "orchestrator.db"

_INIT_SQL = """
CREATE TABLE IF NOT EXISTS pipeline_runs (
    run_id TEXT PRIMARY KEY,
    topic TEXT NOT NULL,
    status TEXT DEFAULT 'pending',
    created_at TEXT,
    completed_at TEXT,
    final_output_path TEXT
);

CREATE TABLE IF NOT EXISTS agent_tasks (
    task_id INTEGER PRIMARY KEY AUTOINCREMENT,
    run_id TEXT NOT NULL,
    agent_name TEXT NOT NULL,
    status TEXT DEFAULT 'pending',
    hermes_run_id TEXT,
    started_at TEXT,
    completed_at TEXT,
    output_summary TEXT,
    error_log TEXT,
    consultation_needed INTEGER DEFAULT 0,
    consultation_data TEXT,
    FOREIGN KEY (run_id) REFERENCES pipeline_runs(run_id)
);

CREATE TABLE IF NOT EXISTS consultations (
    consultation_id INTEGER PRIMARY KEY AUTOINCREMENT,
    run_id TEXT NOT NULL,
    agent_name TEXT NOT NULL,
    question TEXT,
    options TEXT,
    user_choice TEXT,
    resolution TEXT,
    created_at TEXT,
    resolved_at TEXT
);

CREATE INDEX IF NOT EXISTS idx_tasks_run ON agent_tasks(run_id);
CREATE INDEX IF NOT EXISTS idx_tasks_agent ON agent_tasks(agent_name);
CREATE INDEX IF NOT EXISTS idx_consultations_run ON consultations(run_id);
"""


class StateDB:
    def __init__(self, db_path: Path = DEFAULT_DB_PATH):
        self.conn = sqlite3.connect(str(db_path), check_same_thread=False)
        self.conn.row_factory = sqlite3.Row
        self.conn.executescript(_INIT_SQL)
        self.conn.commit()

    # -- pipeline_runs --
    def create_run(self, run_id: str, topic: str):
        self.conn.execute(
            "INSERT INTO pipeline_runs (run_id, topic, status, created_at) VALUES (?, ?, 'pending', ?)",
            (run_id, topic, datetime.now().isoformat()),
        )
        self.conn.commit()

    def update_run_status(self, run_id: str, status: str, final_output_path: str = ""):
        self.conn.execute(
            "UPDATE pipeline_runs SET status=?, completed_at=? WHERE run_id=?",
            (status, datetime.now().isoformat(), run_id),
        )
        self.conn.commit()

    def get_run(self, run_id: str) -> Optional[Dict]:
        cur = self.conn.execute("SELECT * FROM pipeline_runs WHERE run_id=?", (run_id,))
        row = cur.fetchone()
        return dict(row) if row else None

    def get_run_status(self, run_id: str) -> Dict:
        run = self.get_run(run_id)
        if not run:
            return {}
        cur = self.conn.execute(
            "SELECT agent_name, status, output_summary FROM agent_tasks WHERE run_id=?",
            (run_id,),
        )
        tasks = {row["agent_name"]: {"status": row["status"], "summary": row["output_summary"]} for row in cur.fetchall()}
        return {**run, "tasks": tasks}

    def list_runs(self, limit: int = 20) -> List[Dict]:
        cur = self.conn.execute(
            "SELECT run_id, topic, status, created_at, completed_at FROM pipeline_runs ORDER BY created_at DESC LIMIT ?",
            (limit,),
        )
        return [dict(row) for row in cur.fetchall()]

    # -- agent_tasks --
    def create_task(self, run_id: str, agent_name: str) -> int:
        cur = self.conn.execute(
            "INSERT INTO agent_tasks (run_id, agent_name, status, started_at) VALUES (?, ?, 'pending', ?)",
            (run_id, agent_name, datetime.now().isoformat()),
        )
        self.conn.commit()
        return cur.lastrowid

    def update_task_status(
        self,
        task_id: int,
        status: str,
        output_summary: str = "",
        error_log: str = "",
        hermes_run_id: str = "",
    ):
        self.conn.execute(
            """UPDATE agent_tasks
               SET status=?, completed_at=?, output_summary=?, error_log=?, hermes_run_id=?
               WHERE task_id=?""",
            (status, datetime.now().isoformat(), output_summary, error_log, hermes_run_id, task_id),
        )
        self.conn.commit()

    def set_consultation(self, task_id: int, consultation_data: str):
        self.conn.execute(
            "UPDATE agent_tasks SET consultation_needed=1, consultation_data=? WHERE task_id=?",
            (consultation_data, task_id),
        )
        self.conn.commit()

    # -- consultations --
    def create_consultation(self, run_id: str, agent_name: str, question: str, options: str) -> int:
        cur = self.conn.execute(
            "INSERT INTO consultations (run_id, agent_name, question, options, created_at) VALUES (?, ?, ?, ?, ?)",
            (run_id, agent_name, question, options, datetime.now().isoformat()),
        )
        self.conn.commit()
        return cur.lastrowid

    def resolve_consultation(self, consultation_id: int, user_choice: str, resolution: str):
        self.conn.execute(
            "UPDATE consultations SET user_choice=?, resolution=?, resolved_at=? WHERE consultation_id=?",
            (user_choice, resolution, datetime.now().isoformat(), consultation_id),
        )
        self.conn.commit()
