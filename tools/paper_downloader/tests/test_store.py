import sys, os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..'))

import sqlite3
import tempfile
from datetime import datetime

import pytest

from core.store import PaperStore, SCHEMA
from core.models import PaperMeta


@pytest.fixture
def store():
    with tempfile.NamedTemporaryFile(suffix=".db", delete=False) as tmp:
        db_path = tmp.name
    return PaperStore(db_path)


def test_store_init_creates_schema(store):
    cursor = store.conn.execute(
        "SELECT name FROM sqlite_master WHERE type='table'"
    )
    tables = {row[0] for row in cursor.fetchall()}
    assert "papers" in tables
    assert "scan_log" in tables


def test_dedupe_and_insert(store):
    meta1 = PaperMeta(
        source="arxiv",
        source_id="1234.5678",
        title="Paper One",
        doi="10.1000/one",
    )
    meta2 = PaperMeta(
        source="arxiv",
        source_id="1234.5679",
        title="Paper Two",
    )
    meta3 = PaperMeta(
        source="arxiv",
        source_id="1234.5678",
        title="Duplicate Paper",
        doi="10.1000/one",
    )

    inserted = store.dedupe_and_insert([meta1, meta2, meta3])
    assert len(inserted) == 2
    assert hasattr(meta1, "id") and meta1.id is not None
    assert hasattr(meta2, "id") and meta2.id is not None
    assert not hasattr(meta3, "id") or meta3.id is None


def test_get_pending(store):
    meta = PaperMeta(
        source="arxiv",
        source_id="1234.5678",
        title="Pending Paper",
    )
    store.dedupe_and_insert([meta])

    pending = store.get_pending("arxiv")
    assert len(pending) == 1
    assert pending[0].title == "Pending Paper"
    assert pending[0].source_id == "1234.5678"


def test_mark_downloaded(store):
    meta = PaperMeta(
        source="arxiv",
        source_id="1234.5678",
        title="Downloadable Paper",
    )
    store.dedupe_and_insert([meta])
    paper_id = meta.id

    store.mark_downloaded(paper_id, "/tmp/paper.pdf")

    row = store.conn.execute(
        "SELECT status, filepath FROM papers WHERE id = ?", (paper_id,)
    ).fetchone()
    assert row["status"] == "downloaded"
    assert row["filepath"] == "/tmp/paper.pdf"


def test_mark_failed_auto_skip(store):
    meta = PaperMeta(
        source="arxiv",
        source_id="1234.5678",
        title="Failing Paper",
    )
    store.dedupe_and_insert([meta])
    paper_id = meta.id

    store.mark_failed(paper_id, "network error")
    row = store.conn.execute(
        "SELECT status, fail_count FROM papers WHERE id = ?", (paper_id,)
    ).fetchone()
    assert row["status"] == "failed"
    assert row["fail_count"] == 1

    store.mark_failed(paper_id, "network error")
    row = store.conn.execute(
        "SELECT status, fail_count FROM papers WHERE id = ?", (paper_id,)
    ).fetchone()
    assert row["status"] == "failed"
    assert row["fail_count"] == 2

    store.mark_failed(paper_id, "network error")
    row = store.conn.execute(
        "SELECT status, fail_count FROM papers WHERE id = ?", (paper_id,)
    ).fetchone()
    assert row["status"] == "skipped"
    assert row["fail_count"] == 3
