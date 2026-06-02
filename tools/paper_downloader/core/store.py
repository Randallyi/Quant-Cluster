import sqlite3
import json
from datetime import datetime, timezone
from typing import List, Optional
from pathlib import Path

from .models import PaperMeta


SCHEMA = """
CREATE TABLE IF NOT EXISTS papers (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    source TEXT NOT NULL,
    source_id TEXT NOT NULL,
    doi TEXT,
    title TEXT NOT NULL,
    authors TEXT,
    abstract TEXT,
    published_at TEXT,
    year INTEGER,
    pdf_url TEXT,
    landing_url TEXT,
    created_at TEXT DEFAULT (datetime('now')),
    downloaded_at TEXT,
    filepath TEXT,
    status TEXT DEFAULT 'pending'
        CHECK(status IN ('pending', 'downloaded', 'failed', 'skipped')),
    fail_count INTEGER DEFAULT 0,
    last_fail_reason TEXT,
    UNIQUE(source, source_id)
);

CREATE UNIQUE INDEX IF NOT EXISTS idx_doi ON papers(doi) WHERE doi IS NOT NULL;
CREATE INDEX IF NOT EXISTS idx_source_status ON papers(source, status);
CREATE INDEX IF NOT EXISTS idx_published_at ON papers(published_at);
CREATE INDEX IF NOT EXISTS idx_year ON papers(year);

CREATE TABLE IF NOT EXISTS scan_log (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    started_at TEXT DEFAULT (datetime('now')),
    finished_at TEXT,
    source TEXT NOT NULL,
    found_count INTEGER DEFAULT 0,
    new_count INTEGER DEFAULT 0,
    downloaded_count INTEGER DEFAULT 0,
    failed_count INTEGER DEFAULT 0,
    skipped_count INTEGER DEFAULT 0,
    status TEXT DEFAULT 'running'
        CHECK(status IN ('running', 'success', 'partial_failure', 'failed'))
);
"""


class PaperStore:
    def __init__(self, db_path: str):
        self.db_path = db_path
        self.conn = sqlite3.connect(db_path)
        self.conn.row_factory = sqlite3.Row
        self.conn.executescript(SCHEMA)
        self.conn.commit()

    def dedupe_and_insert(self, metas: List[PaperMeta]) -> List[PaperMeta]:
        inserted = []
        for meta in metas:
            authors_json = json.dumps(meta.authors) if meta.authors is not None else None
            published_at_str = meta.published_at.isoformat() if meta.published_at is not None else None

            cursor = self.conn.execute(
                """
                INSERT OR IGNORE INTO papers
                (source, source_id, doi, title, authors, abstract, published_at, year, pdf_url, landing_url)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    meta.source,
                    meta.source_id,
                    meta.doi,
                    meta.title,
                    authors_json,
                    meta.abstract,
                    published_at_str,
                    meta.year,
                    meta.pdf_url,
                    meta.landing_url,
                ),
            )
            if cursor.rowcount > 0:
                meta.id = cursor.lastrowid
                inserted.append(meta)
        self.conn.commit()
        return inserted

    def get_pending(self, source: str, limit: int = 100) -> List[PaperMeta]:
        rows = self.conn.execute(
            "SELECT * FROM papers WHERE source = ? AND status = 'pending' LIMIT ?",
            (source, limit),
        ).fetchall()
        return [self._row_to_meta(row) for row in rows]

    def mark_downloaded(self, paper_id: int, filepath) -> None:
        self.conn.execute(
            """
            UPDATE papers
            SET status = 'downloaded', downloaded_at = datetime('now'), filepath = ?
            WHERE id = ?
            """,
            (str(filepath), paper_id),
        )
        self.conn.commit()

    def mark_failed(self, paper_id: int, reason: str) -> None:
        self.conn.execute(
            """
            UPDATE papers
            SET fail_count = fail_count + 1,
                last_fail_reason = ?,
                status = CASE WHEN fail_count + 1 >= 3 THEN 'skipped' ELSE 'failed' END
            WHERE id = ?
            """,
            (reason, paper_id),
        )
        self.conn.commit()

    def mark_catalogued(self, paper_id: int, reason: str = "catalogued") -> None:
        """Mark a paper as catalogued (recorded but not auto-downloaded).
        
        Different from skipped/failed — the paper is intentionally not downloaded
        based on filtering criteria, but kept in the DB for agent review.
        """
        self.conn.execute(
            """
            UPDATE papers
            SET status = 'skipped', last_fail_reason = ?
            WHERE id = ?
            """,
            (f"catalogued: {reason}", paper_id),
        )
        self.conn.commit()

    def bulk_catalogue(self, paper_ids: List[int], reason: str = "catalogued") -> int:
        """Bulk mark papers as catalogued. Much faster than calling mark_catalogue
        in a loop because it uses a single transaction."""
        if not paper_ids:
            return 0
        placeholders = ",".join("?" * len(paper_ids))
        self.conn.execute(
            f"""
            UPDATE papers
            SET status = 'skipped', last_fail_reason = ?
            WHERE id IN ({placeholders})
            """,
            (f"catalogued: {reason}",) + tuple(paper_ids),
        )
        self.conn.commit()
        return len(paper_ids)

    def get_latest_published_at(self, source: str) -> Optional[datetime]:
        row = self.conn.execute(
            "SELECT MAX(published_at) as max_published FROM papers WHERE source = ?",
            (source,),
        ).fetchone()
        if row and row["max_published"]:
            dt = datetime.fromisoformat(row["max_published"])
            if dt.tzinfo is None:
                dt = dt.replace(tzinfo=timezone.utc)
            return dt
        return None

    def _row_to_meta(self, row: sqlite3.Row) -> PaperMeta:
        meta = PaperMeta(
            source=row["source"],
            source_id=row["source_id"],
            doi=row["doi"],
            title=row["title"],
            authors=json.loads(row["authors"]) if row["authors"] else None,
            abstract=row["abstract"],
            published_at=datetime.fromisoformat(row["published_at"]) if row["published_at"] else None,
            year=row["year"],
            pdf_url=row["pdf_url"],
            landing_url=row["landing_url"],
        )
        meta.id = row["id"]
        return meta
