"""CacheManager — read-through / write-through SQLite cache for historical bars."""
import hashlib
import json
import logging
import time
from typing import Optional

import sqlite3

from models import Bar, HistoricalDataRequest
from cache.db import DEFAULT_DB_PATH, init_db

logger = logging.getLogger(__name__)

# TTL (seconds) by barSizeSetting
_TTL_MAP: dict[str, int] = {
    "1 secs": 60, "5 secs": 60, "10 secs": 60, "15 secs": 60, "30 secs": 60,
    "1 min": 300, "2 mins": 300, "3 mins": 300, "5 mins": 300,
    "10 mins": 300, "15 mins": 300, "20 mins": 300, "30 mins": 300,
    "1 hour": 1800, "2 hours": 1800, "3 hours": 1800, "4 hours": 1800, "8 hours": 1800,
    "1 day": 3600, "1 week": 86400, "1 month": 86400,
}

_DEFAULT_TTL = 3600

_INSERT_SQL = """
INSERT INTO cache_entries (
    cache_key, symbol, sec_type, exchange, currency,
    bar_size, what_to_show, use_rth, end_date_time, duration,
    source, bars_json, row_count, created_at, expires_at
) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
ON CONFLICT(cache_key) DO UPDATE SET
    bars_json=excluded.bars_json,
    row_count=excluded.row_count,
    created_at=excluded.created_at,
    expires_at=excluded.expires_at,
    source=excluded.source
"""

_SELECT_SQL = """
SELECT bars_json, expires_at, source FROM cache_entries WHERE cache_key = ?
"""

_DELETE_SQL = "DELETE FROM cache_entries WHERE cache_key = ?"

_STATS_SQL = """
SELECT
    source,
    COUNT(*) AS total_entries,
    SUM(CASE WHEN expires_at > ? THEN 1 ELSE 0 END) AS valid_entries,
    SUM(row_count) AS total_rows
FROM cache_entries
GROUP BY source
"""

_OVERALL_STATS_SQL = """
SELECT
    COUNT(*) AS total_entries,
    SUM(CASE WHEN expires_at > ? THEN 1 ELSE 0 END) AS valid_entries,
    SUM(row_count) AS total_rows
FROM cache_entries
"""

_PRUNE_SQL = "DELETE FROM cache_entries WHERE expires_at <= ?"


class CacheManager:
    """SQLite-backed cache for historical bar data."""

    def __init__(self, db_path: str = DEFAULT_DB_PATH):
        self._conn: sqlite3.Connection = init_db(db_path)
        self._hits = 0
        self._misses = 0

    # ------------------------------------------------------------------
    # Key generation
    # ------------------------------------------------------------------
    @staticmethod
    def _compute_key(request: HistoricalDataRequest, source: str = "ibkr") -> str:
        """Deterministic cache key from request parameters."""
        c = request.contract
        parts = [
            source,
            c.symbol, c.secType, c.exchange, c.currency,
            c.expiry, str(c.strike), c.right, c.multiplier,
            c.primaryExchange, str(c.includeExpired),
            request.barSizeSetting, request.durationStr,
            request.whatToShow, str(request.useRTH),
            request.endDateTime,
        ]
        payload = "|".join(parts)
        return hashlib.sha256(payload.encode()).hexdigest()

    @staticmethod
    def _ttl(request: HistoricalDataRequest) -> int:
        return _TTL_MAP.get(request.barSizeSetting, _DEFAULT_TTL)

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------
    def get(self, request: HistoricalDataRequest, source: str = "ibkr") -> Optional[list[Bar]]:
        """Return cached bars if present and not expired."""
        key = self._compute_key(request, source=source)
        now = time.time()

        cur = self._conn.execute(_SELECT_SQL, (key,))
        row = cur.fetchone()
        if row is None:
            self._misses += 1
            return None

        bars_json, expires_at, _ = row
        if expires_at <= now:
            # Expired — treat as miss and delete
            self._conn.execute(_DELETE_SQL, (key,))
            self._conn.commit()
            self._misses += 1
            return None

        self._hits += 1
        bars_raw = json.loads(bars_json)
        return [Bar(**b) for b in bars_raw]

    def set(self, request: HistoricalDataRequest, bars: list[Bar], source: str = "ibkr") -> None:
        """Write bars to cache."""
        key = self._compute_key(request, source=source)
        now = time.time()
        ttl = self._ttl(request)
        c = request.contract

        bars_json = json.dumps([b.model_dump() for b in bars])

        self._conn.execute(
            _INSERT_SQL,
            (
                key,
                c.symbol,
                c.secType,
                c.exchange,
                c.currency,
                request.barSizeSetting,
                request.whatToShow,
                int(request.useRTH),
                request.endDateTime,
                request.durationStr,
                source,
                bars_json,
                len(bars),
                now,
                now + ttl,
            ),
        )
        self._conn.commit()
        logger.debug("Cached %d bars for %s (%s)", len(bars), c.symbol, key[:8])

    def invalidate(self, request: HistoricalDataRequest, source: str = "ibkr") -> None:
        """Remove a specific entry from cache."""
        key = self._compute_key(request, source=source)
        self._conn.execute(_DELETE_SQL, (key,))
        self._conn.commit()
        logger.debug("Invalidated cache key %s", key[:8])

    def prune(self) -> int:
        """Delete expired entries. Returns number pruned."""
        cur = self._conn.execute(_PRUNE_SQL, (time.time(),))
        self._conn.commit()
        return cur.rowcount

    def stats(self) -> dict:
        """Cache statistics including per-source breakdown."""
        now = time.time()
        per_source: dict[str, dict] = {}

        cur = self._conn.execute(_STATS_SQL, (now,))
        for row in cur.fetchall():
            src, total, valid, rows = row
            per_source[src] = {
                "entries_total": total,
                "entries_valid": valid,
                "total_rows": rows or 0,
            }

        # Also fetch overall totals for top-level compatibility
        cur = self._conn.execute(_OVERALL_STATS_SQL, (now,))
        overall = cur.fetchone()
        total_entries, valid_entries, total_rows = overall if overall else (0, 0, 0)

        total_reqs = self._hits + self._misses
        return {
            "entries_total": total_entries,
            "entries_valid": valid_entries,
            "total_rows": total_rows or 0,
            "sources": per_source,
            "hits": self._hits,
            "misses": self._misses,
            "hit_rate": round(self._hits / total_reqs, 3) if total_reqs else 0.0,
        }
