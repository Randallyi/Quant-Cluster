"""Tests for cache layer source column migration and per-source behaviour."""
import sqlite3
import tempfile
from pathlib import Path

from cache.db import init_db
from cache.manager import CacheManager
from models import Bar, Contract, HistoricalDataRequest


def _make_request(symbol: str = "AAPL") -> HistoricalDataRequest:
    return HistoricalDataRequest(
        contract=Contract(
            symbol=symbol,
            secType="STK",
            exchange="SMART",
            currency="USD",
        ),
        durationStr="1 D",
        barSizeSetting="1 min",
    )


def _make_bars(n: int = 3) -> list[Bar]:
    return [
        Bar(
            date=f"2024-01-0{i}T09:30:00",
            open=100.0 + i,
            high=101.0 + i,
            low=99.0 + i,
            close=100.5 + i,
            volume=1000 + i * 100,
            wap=100.25 + i,
            count=10 + i,
        )
        for i in range(1, n + 1)
    ]


def test_migration_adds_source_column():
    """An existing DB without the source column should be migrated automatically."""
    with tempfile.TemporaryDirectory() as tmpdir:
        db_path = Path(tmpdir) / "old_cache.db"

        # Create a legacy schema (no source column)
        conn = sqlite3.connect(str(db_path), check_same_thread=False)
        conn.execute(
            """
            CREATE TABLE cache_entries (
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
                bars_json           TEXT NOT NULL,
                row_count           INTEGER NOT NULL,
                created_at          REAL    NOT NULL,
                expires_at          REAL    NOT NULL
            )
            """
        )
        conn.commit()
        conn.close()

        # Re-opening via init_db should trigger the migration
        conn2 = init_db(str(db_path))
        cur = conn2.execute("PRAGMA table_info(cache_entries)")
        columns = [row[1] for row in cur.fetchall()]
        assert "source" in columns, f"Expected 'source' in columns, got {columns}"
        conn2.close()


def test_different_sources_produce_different_keys():
    """Same request with different source values must yield distinct cache keys."""
    req = _make_request()

    key_ibkr = CacheManager._compute_key(req, source="ibkr")
    key_yf = CacheManager._compute_key(req, source="yfinance")

    assert key_ibkr != key_yf, "Cache keys for different sources should be unique"


def test_stats_returns_per_source_grouping():
    """stats() should group metrics by source."""
    with tempfile.TemporaryDirectory() as tmpdir:
        db_path = Path(tmpdir) / "test_cache.db"
        cm = CacheManager(str(db_path))

        req = _make_request()
        bars = _make_bars(3)

        # Write same request under two different sources
        cm.set(req, bars, source="ibkr")
        cm.set(req, bars, source="yfinance")

        stats = cm.stats()

        assert "sources" in stats
        src_stats = stats["sources"]
        assert "ibkr" in src_stats
        assert "yfinance" in src_stats

        assert src_stats["ibkr"]["entries_total"] == 1
        assert src_stats["ibkr"]["total_rows"] == 3
        assert src_stats["yfinance"]["entries_total"] == 1
        assert src_stats["yfinance"]["total_rows"] == 3

        assert stats["entries_total"] == 2
        assert stats["total_rows"] == 6
