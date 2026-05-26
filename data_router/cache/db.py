"""SQLite database layer for the historical-data cache."""
import logging
import os
import sqlite3
from pathlib import Path

logger = logging.getLogger(__name__)

DEFAULT_DB_PATH = os.getenv("CACHE_DB", "/app/cache/data_cache.db")

_INIT_SQL = """
CREATE TABLE IF NOT EXISTS cache_entries (
    cache_key           TEXT PRIMARY KEY,
    symbol              TEXT NOT NULL,
    sec_type            TEXT NOT NULL,
    exchange            TEXT NOT NULL,
    currency            TEXT NOT NULL,
    bar_size            TEXT NOT NULL,
    what_to_show        TEXT NOT NULL,
    use_rth             INTEGER NOT NULL,
    end_date_time       TEXT,
    duration            TEXT NOT NULL,
    source              TEXT DEFAULT 'ibkr',
    bars_json           TEXT NOT NULL,
    row_count           INTEGER NOT NULL,
    created_at          REAL    NOT NULL,
    expires_at          REAL    NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_cache_lookup
ON cache_entries(symbol, sec_type, bar_size, what_to_show, use_rth);

CREATE INDEX IF NOT EXISTS idx_cache_expiry
ON cache_entries(expires_at);
"""

_SOURCE_INDEX_SQL = """
CREATE INDEX IF NOT EXISTS idx_source
ON cache_entries(source);
"""


def _migrate_add_source_column(conn: sqlite3.Connection) -> None:
    """Add 'source' column to legacy schema that lacks it."""
    cur = conn.execute("PRAGMA table_info(cache_entries)")
    columns = [row[1] for row in cur.fetchall()]
    if "source" not in columns:
        logger.info("Migrating cache_entries: adding source column")
        conn.execute("ALTER TABLE cache_entries ADD COLUMN source TEXT DEFAULT 'ibkr'")
        conn.commit()
        logger.info("Migration complete: source column added")


def init_db(db_path: str = DEFAULT_DB_PATH) -> sqlite3.Connection:
    """Open (and create if needed) the SQLite cache database."""
    Path(db_path).parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(db_path, check_same_thread=False)
    conn.executescript(_INIT_SQL)
    conn.commit()
    _migrate_add_source_column(conn)
    conn.executescript(_SOURCE_INDEX_SQL)
    conn.commit()
    logger.info("Cache DB ready: %s", db_path)
    return conn
