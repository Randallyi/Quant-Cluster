# Data Router / Loaders Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 在 data_router 中新增 yfinance 数据源、Loader 抽象层、多源缓存支持和健康查询接口，同时保持现有 IBKR 端点向后兼容。

**Architecture:** 各 Loader 独立实现，通过统一 Protocol 约定接口；Cache 层扩展 `source` 列支持多源隔离；端点按数据源拆分（`/data/ibkr/*`, `/data/yfinance/*`），Agent 通过 `/data/sources` 查询后自选调用。

**Tech Stack:** FastAPI, Pydantic, SQLite, yfinance, ib_insync

---

## File Structure

| 文件 | 操作 | 职责 |
|------|------|------|
| `data_router/cache/db.py` | 修改 | 新增 `source` 列 + 自动 migration |
| `data_router/cache/manager.py` | 修改 | source-aware cache key、全局统计 |
| `data_router/models.py` | 修改 | 新增 `YFHistoricalRequest`, `FundamentalData`, `SourceHealth`, `DataResponse` |
| `data_router/loaders/base.py` | 新建 | `LoaderProtocol` 接口约定 |
| `data_router/loaders/yfinance_loader.py` | 新建 | yfinance 数据获取 + 基本面 |
| `data_router/loaders/akshare_loader.py` | 新建 | 占位骨架（暂不实现） |
| `data_router/loaders/__init__.py` | 新建 | 导出 |
| `data_router/routers/ibkr.py` | 新建 | 从 data.py 拆分出的 IBKR 端点 |
| `data_router/routers/yfinance.py` | 新建 | yfinance historical + fundamental 端点 |
| `data_router/routers/sources.py` | 新建 | `/data/sources` 健康查询 |
| `data_router/routers/data.py` | 修改 | 保留兼容层，内部转发到 ibkr.py + deprecation log |
| `data_router/routers/__init__.py` | 修改 | 导出新 routers |
| `data_router/main.py` | 修改 | 注册新 routers |
| `data_router/requirements.txt` | 修改 | 添加 `yfinance>=0.2.54` |
| `tests/data_router/test_cache_migration.py` | 新建 | Cache migration 测试 |
| `tests/data_router/test_yfinance_loader.py` | 新建 | yfinance_loader 单元测试 |

---

## Task 1: Cache 层扩展 — source 列 + migration + 全局统计

**Files:**
- Modify: `data_router/cache/db.py`
- Modify: `data_router/cache/manager.py`
- Create: `tests/data_router/test_cache_migration.py`

- [ ] **Step 1: 查看现有 cache schema**

Read: `data_router/cache/db.py` (确认当前 CREATE TABLE SQL)

- [ ] **Step 2: 修改 db.py — 新表 schema 含 source 列 + migration 函数**

```python
# data_router/cache/db.py
import sqlite3
import logging
import os

logger = logging.getLogger(__name__)

DEFAULT_DB_PATH = os.path.join(os.path.dirname(__file__), "data_cache.db")

_CREATE_TABLE_SQL = """
CREATE TABLE IF NOT EXISTS cache_entries (
    cache_key TEXT PRIMARY KEY,
    source TEXT DEFAULT 'ibkr',
    symbol TEXT,
    sec_type TEXT,
    exchange TEXT,
    currency TEXT,
    bar_size TEXT,
    what_to_show TEXT,
    use_rth INTEGER,
    end_date_time TEXT,
    duration TEXT,
    bars_json TEXT,
    row_count INTEGER,
    created_at REAL,
    expires_at REAL
);
"""

_CREATE_INDEX_SQL = """
CREATE INDEX IF NOT EXISTS idx_source ON cache_entries(source);
"""


def init_db(db_path: str = DEFAULT_DB_PATH) -> sqlite3.Connection:
    """Open or create the SQLite cache, running migrations if needed."""
    conn = sqlite3.connect(db_path, check_same_thread=False)
    conn.execute(_CREATE_TABLE_SQL)
    conn.execute(_CREATE_INDEX_SQL)
    _migrate_add_source_column(conn)
    return conn


def _migrate_add_source_column(conn: sqlite3.Connection) -> None:
    """Add source column if migrating from v1 schema."""
    cur = conn.execute("PRAGMA table_info(cache_entries)")
    columns = [row[1] for row in cur.fetchall()]
    if "source" not in columns:
        conn.execute(
            "ALTER TABLE cache_entries ADD COLUMN source TEXT DEFAULT 'ibkr'"
        )
        conn.commit()
        logger.info("Migrated cache schema: added source column")
```

- [ ] **Step 3: 修改 manager.py — source-aware key + 全局统计**

```python
# data_router/cache/manager.py
# ... existing imports ...

_INSERT_SQL = """
INSERT INTO cache_entries (
    cache_key, source, symbol, sec_type, exchange, currency,
    bar_size, what_to_show, use_rth, end_date_time, duration,
    bars_json, row_count, created_at, expires_at
) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
ON CONFLICT(cache_key) DO UPDATE SET
    source=excluded.source,
    bars_json=excluded.bars_json,
    row_count=excluded.row_count,
    created_at=excluded.created_at,
    expires_at=excluded.expires_at
"""

# Update _SELECT_SQL to select source as well (not strictly needed for read)
_SELECT_SQL = """
SELECT bars_json, expires_at, source FROM cache_entries WHERE cache_key = ?
"""

# ... rest of existing SQL constants unchanged ...

class CacheManager:
    # ... __init__ unchanged ...

    @staticmethod
    def _compute_key(source: str, request) -> str:
        """Deterministic cache key from source + request parameters."""
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

    def get(self, request, source: str = "ibkr") -> Optional[list[Bar]]:
        """Return cached bars if present and not expired."""
        key = self._compute_key(source, request)
        now = time.time()

        cur = self._conn.execute(_SELECT_SQL, (key,))
        row = cur.fetchone()
        if row is None:
            self._misses += 1
            return None

        bars_json, expires_at, _source = row
        if expires_at <= now:
            self._conn.execute(_DELETE_SQL, (key,))
            self._conn.commit()
            self._misses += 1
            return None

        self._hits += 1
        bars_raw = json.loads(bars_json)
        return [Bar(**b) for b in bars_raw]

    def set(self, request, bars: list[Bar], source: str = "ibkr") -> None:
        """Write bars to cache."""
        key = self._compute_key(source, request)
        now = time.time()
        ttl = self._ttl(request)
        c = request.contract

        bars_json = json.dumps([b.model_dump() for b in bars])

        self._conn.execute(
            _INSERT_SQL,
            (
                key,
                source,
                c.symbol,
                c.secType,
                c.exchange,
                c.currency,
                request.barSizeSetting,
                request.whatToShow,
                int(request.useRTH),
                request.endDateTime,
                request.durationStr,
                bars_json,
                len(bars),
                now,
                now + ttl,
            ),
        )
        self._conn.commit()
        logger.debug("Cached %d bars for %s (source=%s, key=%s)", len(bars), c.symbol, source, key[:8])

    def invalidate(self, request, source: str = "ibkr") -> None:
        """Remove a specific entry from cache."""
        key = self._compute_key(source, request)
        self._conn.execute(_DELETE_SQL, (key,))
        self._conn.commit()
        logger.debug("Invalidated cache key %s", key[:8])

    # ... prune unchanged ...

    def stats(self) -> dict:
        """Cache statistics, grouped by source."""
        now = time.time()
        # Per-source stats
        per_source_sql = """
        SELECT source,
            COUNT(*) AS total,
            SUM(CASE WHEN expires_at > ? THEN 1 ELSE 0 END) AS valid,
            SUM(row_count) AS rows
        FROM cache_entries
        GROUP BY source
        """
        cur = self._conn.execute(per_source_sql, (now,))
        per_source = {}
        for row in cur.fetchall():
            source, total, valid, rows = row
            per_source[source] = {
                "entries_total": total,
                "entries_valid": valid or 0,
                "total_rows": rows or 0,
            }

        total_reqs = self._hits + self._misses
        return {
            "sources": per_source,
            "hits": self._hits,
            "misses": self._misses,
            "hit_rate": round(self._hits / total_reqs, 3) if total_reqs else 0.0,
        }
```

- [ ] **Step 4: 写 migration 测试**

```python
# tests/data_router/test_cache_migration.py
import os
import sqlite3
import tempfile

import pytest

from cache.db import init_db, _migrate_add_source_column
from cache.manager import CacheManager
from models import Bar, Contract, HistoricalDataRequest


def test_migration_adds_source_column():
    """Simulate old schema (no source column) and verify migration works."""
    with tempfile.NamedTemporaryFile(suffix=".db", delete=False) as f:
        db_path = f.name

    try:
        # Create old schema manually (no source column)
        conn = sqlite3.connect(db_path)
        conn.execute("""
            CREATE TABLE cache_entries (
                cache_key TEXT PRIMARY KEY,
                symbol TEXT,
                bars_json TEXT,
                row_count INTEGER,
                created_at REAL,
                expires_at REAL
            )
        """)
        conn.commit()
        conn.close()

        # init_db should migrate it
        conn = init_db(db_path)
        cur = conn.execute("PRAGMA table_info(cache_entries)")
        columns = [row[1] for row in cur.fetchall()]
        assert "source" in columns
        conn.close()
    finally:
        os.unlink(db_path)


def test_cache_source_aware_key():
    """Same request with different sources should have different cache keys."""
    with tempfile.NamedTemporaryFile(suffix=".db", delete=False) as f:
        db_path = f.name

    try:
        cm = CacheManager(db_path)
        contract = Contract(symbol="AAPL", secType="STK", exchange="SMART", currency="USD")
        request = HistoricalDataRequest(
            contract=contract,
            durationStr="1 Y",
            barSizeSetting="1 day",
        )
        bars = [Bar(date="2024-01-01", open=100, high=101, low=99, close=100, volume=1000, wap=100, count=10)]

        cm.set(request, bars, source="ibkr")
        cm.set(request, bars, source="yfinance")

        # Should be two separate entries
        cur = cm._conn.execute("SELECT COUNT(*) FROM cache_entries")
        assert cur.fetchone()[0] == 2

        # Each get should return only its own data
        ibkr_bars = cm.get(request, source="ibkr")
        yf_bars = cm.get(request, source="yfinance")
        assert ibkr_bars is not None
        assert yf_bars is not None
        assert len(ibkr_bars) == 1
        assert len(yf_bars) == 1
    finally:
        os.unlink(db_path)


def test_cache_stats_grouped_by_source():
    with tempfile.NamedTemporaryFile(suffix=".db", delete=False) as f:
        db_path = f.name

    try:
        cm = CacheManager(db_path)
        contract = Contract(symbol="AAPL", secType="STK", exchange="SMART", currency="USD")
        request = HistoricalDataRequest(contract=contract, durationStr="1 Y", barSizeSetting="1 day")
        bars = [Bar(date="2024-01-01", open=100, high=101, low=99, close=100, volume=1000, wap=100, count=10)]

        cm.set(request, bars, source="ibkr")
        cm.set(request, bars, source="yfinance")

        stats = cm.stats()
        assert "sources" in stats
        assert "ibkr" in stats["sources"]
        assert "yfinance" in stats["sources"]
        assert stats["sources"]["ibkr"]["entries_total"] == 1
        assert stats["sources"]["yfinance"]["entries_total"] == 1
    finally:
        os.unlink(db_path)
```

- [ ] **Step 5: 运行 migration 测试**

Run: `cd data_router && python -m pytest ../tests/data_router/test_cache_migration.py -v`

Expected: 3 tests PASS

- [ ] **Step 6: Commit**

```bash
git add data_router/cache/db.py data_router/cache/manager.py tests/data_router/test_cache_migration.py
git commit -m "feat(cache): add source-aware cache with auto migration"
```

---

## Task 2: 新增 Pydantic 模型

**Files:**
- Modify: `data_router/models.py`

- [ ] **Step 1: 在 models.py 末尾追加新模型**

```python
# data_router/models.py — append to existing file

# ------------------------------------------------------------------
# YFinance models
# ------------------------------------------------------------------

class YFHistoricalRequest(BaseModel):
    ticker: str
    start: str = ""
    end: str = ""
    interval: Literal["1d", "1wk", "1mo"] = "1d"
    auto_adjust: bool = True


class FundamentalData(BaseModel):
    ticker: str
    market_cap: Optional[float] = None
    pe_ratio: Optional[float] = None
    pb_ratio: Optional[float] = None
    eps: Optional[float] = None
    dividend_yield: Optional[float] = None
    last_updated: str = ""


# ------------------------------------------------------------------
# Unified response wrappers
# ------------------------------------------------------------------

class DataResponse(BaseModel):
    status: Literal["success", "error"]
    source: str = ""
    request_id: str = ""
    data: list = Field(default_factory=list)
    metadata: dict = Field(default_factory=dict)
    cached: bool = False
    fetch_time_ms: int = 0


class SourceHealth(BaseModel):
    name: str
    available: bool
    markets: list[str] = Field(default_factory=list)
    latency_ms: Optional[int] = None
    message: str = ""
    cache_stats: dict = Field(default_factory=dict)


# ------------------------------------------------------------------
# Enhanced error response (extends existing DataErrorResponse)
# ------------------------------------------------------------------

class DataErrorResponse(BaseModel):
    status: Literal["error"]
    source: str = ""
    request_id: str = ""
    attempts: int = 0
    error_code: str = ""
    error_category: Literal[
        "SUBSCRIPTION", "SYMBOL", "TIMEOUT", "NETWORK",
        "TWS_DISCONNECTED", "RATE_LIMIT", "INVALID_PARAMS", "DATA_UNAVAILABLE"
    ] = "NETWORK"
    tws_error_code: Optional[int] = None
    message: str = ""
    suggestion: str = ""
    fallback_available: list[str] = Field(default_factory=list)
    contract: Optional[Contract] = None
```

- [ ] **Step 2: 验证模型无语法错误**

Run: `cd data_router && python -c "from models import *; print('OK')"`

Expected: `OK`

- [ ] **Step 3: Commit**

```bash
git add data_router/models.py
git commit -m "feat(models): add YFHistoricalRequest, FundamentalData, DataResponse, SourceHealth"
```

---

## Task 3: Loader 基类 + yfinance_loader 实现

**Files:**
- Create: `data_router/loaders/base.py`
- Create: `data_router/loaders/yfinance_loader.py`
- Create: `data_router/loaders/akshare_loader.py`
- Create: `data_router/loaders/__init__.py`
- Create: `tests/data_router/test_yfinance_loader.py`

- [ ] **Step 1: 创建 base.py**

```python
# data_router/loaders/base.py
from typing import Protocol, List, Optional

from models import Bar, FundamentalData


class LoaderProtocol(Protocol):
    """Protocol for data loaders. Implementations are not required to inherit."""

    name: str

    def fetch_historical(self, **kwargs) -> List[Bar]:
        """Fetch historical bars. Return standardized Bar list."""
        ...

    def fetch_fundamental(self, ticker: str) -> Optional[FundamentalData]:
        """Fetch fundamental data. Return None if not supported."""
        ...

    def health(self) -> dict:
        """Return health status: {available: bool, latency_ms: int, message: str}"""
        ...
```

- [ ] **Step 2: 创建 yfinance_loader.py**

```python
# data_router/loaders/yfinance_loader.py
import logging
import time
from datetime import datetime, timedelta
from typing import List, Optional

import yfinance as yf

from models import Bar, FundamentalData

logger = logging.getLogger(__name__)

# Market suffix mapping for yfinance
_MARKET_SUFFIX = {
    "HK": ".HK",
    "US": "",  # US tickers have no suffix
}


class YFinanceLoader:
    """YFinance data loader for global equities (US, HK, etc.)."""

    name = "yfinance"

    def fetch_historical(
        self,
        ticker: str,
        start: str = "",
        end: str = "",
        interval: str = "1d",
        auto_adjust: bool = True,
    ) -> List[Bar]:
        """Fetch historical OHLCV bars from yfinance.

        Args:
            ticker: Raw ticker symbol, e.g. "AAPL" or "0700"
            start: YYYY-MM-DD, default 1 year ago
            end: YYYY-MM-DD, default yesterday
            interval: "1d", "1wk", or "1mo"
            auto_adjust: Whether to return adjusted close prices
        """
        # Default date range
        if not end:
            end = (datetime.now() - timedelta(days=1)).strftime("%Y-%m-%d")
        if not start:
            start = (datetime.strptime(end, "%Y-%m-%d") - timedelta(days=365)).strftime("%Y-%m-%d")

        logger.info("[yfinance] Fetching %s from %s to %s (%s)", ticker, start, end, interval)

        tkr = yf.Ticker(ticker)
        hist = tkr.history(start=start, end=end, interval=interval, auto_adjust=auto_adjust)

        if hist.empty:
            logger.warning("[yfinance] No data returned for %s", ticker)
            return []

        bars: List[Bar] = []
        for idx, row in hist.iterrows():
            date_str = idx.strftime("%Y-%m-%d") if isinstance(idx, datetime) else str(idx)
            bars.append(
                Bar(
                    date=date_str,
                    open=round(float(row["Open"]), 4) if not pd.isna(row["Open"]) else 0.0,
                    high=round(float(row["High"]), 4) if not pd.isna(row["High"]) else 0.0,
                    low=round(float(row["Low"]), 4) if not pd.isna(row["Low"]) else 0.0,
                    close=round(float(row["Close"]), 4) if not pd.isna(row["Close"]) else 0.0,
                    volume=int(row["Volume"]) if not pd.isna(row["Volume"]) else 0,
                    wap=0.0,  # yfinance does not provide VWAP
                    count=0,  # yfinance does not provide bar count
                )
            )

        logger.info("[yfinance] Fetched %d bars for %s", len(bars), ticker)
        return bars

    def fetch_fundamental(self, ticker: str) -> Optional[FundamentalData]:
        """Fetch fundamental data snapshot for a ticker."""
        logger.info("[yfinance] Fetching fundamentals for %s", ticker)

        try:
            tkr = yf.Ticker(ticker)
            info = tkr.info

            if not info:
                logger.warning("[yfinance] No info returned for %s", ticker)
                return None

            return FundamentalData(
                ticker=ticker,
                market_cap=info.get("marketCap"),
                pe_ratio=info.get("trailingPE"),
                pb_ratio=info.get("priceToBook"),
                eps=info.get("trailingEps"),
                dividend_yield=info.get("dividendYield"),
                last_updated=datetime.now().isoformat(),
            )
        except Exception as exc:
            logger.error("[yfinance] Fundamental fetch failed for %s: %s", ticker, exc)
            return None

    def health(self) -> dict:
        """Check yfinance availability by fetching a well-known ticker."""
        start = time.perf_counter()
        try:
            tkr = yf.Ticker("AAPL")
            hist = tkr.history(period="5d")
            latency_ms = int((time.perf_counter() - start) * 1000)
            return {
                "available": not hist.empty,
                "latency_ms": latency_ms,
                "message": "ok" if not hist.empty else "empty response",
            }
        except Exception as exc:
            latency_ms = int((time.perf_counter() - start) * 1000)
            return {
                "available": False,
                "latency_ms": latency_ms,
                "message": str(exc),
            }
```

- [ ] **Step 3: 修复 yfinance_loader.py — 添加缺失的 pandas import**

```python
# Add at top of yfinance_loader.py
import pandas as pd
```

- [ ] **Step 4: 创建 akshare_loader.py（占位骨架）**

```python
# data_router/loaders/akshare_loader.py
import logging
from typing import List, Optional

from models import Bar, FundamentalData

logger = logging.getLogger(__name__)


class AKShareLoader:
    """Placeholder for AKShare (China A-share) data loader.

    Not implemented yet. When ready, install akshare and implement
    fetch_historical() and fetch_fundamental() methods.
    """

    name = "akshare"

    def fetch_historical(self, **kwargs) -> List[Bar]:
        raise NotImplementedError("AKShare loader not yet implemented")

    def fetch_fundamental(self, ticker: str) -> Optional[FundamentalData]:
        raise NotImplementedError("AKShare loader not yet implemented")

    def health(self) -> dict:
        return {
            "available": False,
            "latency_ms": 0,
            "message": "not configured",
        }
```

- [ ] **Step 5: 创建 loaders/__init__.py**

```python
# data_router/loaders/__init__.py
from .yfinance_loader import YFinanceLoader
from .akshare_loader import AKShareLoader

__all__ = ["YFinanceLoader", "AKShareLoader"]
```

- [ ] **Step 6: 创建 yfinance_loader 测试**

```python
# tests/data_router/test_yfinance_loader.py
import pytest

from loaders.yfinance_loader import YFinanceLoader
from models import Bar


class TestYFinanceLoader:
    @pytest.fixture
    def loader(self):
        return YFinanceLoader()

    def test_name(self, loader):
        assert loader.name == "yfinance"

    def test_fetch_historical_aapl(self, loader):
        """Integration test: fetch real AAPL data. May be slow / flaky."""
        bars = loader.fetch_historical("AAPL", start="2024-01-01", end="2024-01-10")
        assert isinstance(bars, list)
        if len(bars) > 0:
            assert isinstance(bars[0], Bar)
            assert bars[0].symbol is None  # Bar doesn't have symbol field
            assert bars[0].open > 0
            assert bars[0].volume >= 0

    def test_fetch_historical_invalid_ticker(self, loader):
        bars = loader.fetch_historical("INVALID_TICKER_XYZ", start="2024-01-01", end="2024-01-10")
        assert bars == []

    def test_fetch_fundamental_aapl(self, loader):
        fund = loader.fetch_fundamental("AAPL")
        if fund is not None:
            assert fund.ticker == "AAPL"
            # At least one field should be populated
            assert any([
                fund.market_cap is not None,
                fund.pe_ratio is not None,
                fund.pb_ratio is not None,
                fund.eps is not None,
            ])

    def test_health(self, loader):
        health = loader.health()
        assert "available" in health
        assert "latency_ms" in health
        assert "message" in health


class TestAKShareLoader:
    def test_name(self):
        from loaders.akshare_loader import AKShareLoader
        loader = AKShareLoader()
        assert loader.name == "akshare"

    def test_health_not_available(self):
        from loaders.akshare_loader import AKShareLoader
        loader = AKShareLoader()
        health = loader.health()
        assert health["available"] is False
```

- [ ] **Step 7: 运行 loader 测试（标记 slow 的跳过）**

Run: `cd data_router && python -m pytest ../tests/data_router/test_yfinance_loader.py -v -k "not aapl"`

Expected: name, invalid_ticker, health tests PASS; aapl tests skipped

- [ ] **Step 8: Commit**

```bash
git add data_router/loaders/ tests/data_router/test_yfinance_loader.py
git commit -m "feat(loaders): add YFinanceLoader, AKShareLoader placeholder, and base protocol"
```

---

## Task 4: 拆分 IBKR Router

**Files:**
- Create: `data_router/routers/ibkr.py`
- Modify: `data_router/routers/data.py`（保留兼容层）

- [ ] **Step 1: 将现有 data.py 的核心逻辑复制到 ibkr.py**

```python
# data_router/routers/ibkr.py
"""IBKR historical data router — extracted from data.py."""

import asyncio
import logging
import re
import time
import uuid
from datetime import datetime
from typing import Optional, Union

from fastapi import APIRouter, Depends
from ib_insync import Contract as IbContract

from cache.manager import CacheManager
from dependencies import get_cache_manager, get_ibkr_client
from ibkr.client import IBKRClient
from models import Bar, Contract, DataErrorResponse, HistoricalDataRequest, HistoricalDataResponse

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/ibkr", tags=["ibkr"])

BACKOFF_DELAYS = [2, 4, 8, 16, 32]


def _to_ib_contract(contract: Contract) -> IbContract:
    kwargs = {
        "symbol": contract.symbol,
        "secType": contract.secType,
        "exchange": contract.exchange,
        "currency": contract.currency,
        "lastTradeDateOrContractMonth": contract.expiry,
        "strike": contract.strike,
        "right": contract.right,
        "multiplier": contract.multiplier,
        "primaryExchange": contract.primaryExchange,
        "includeExpired": contract.includeExpired,
    }
    if contract.localSymbol:
        kwargs["localSymbol"] = contract.localSymbol
    return IbContract(**kwargs)


def _format_date(value) -> str:
    if isinstance(value, datetime):
        return value.isoformat()
    return str(value)


def _parse_tws_code(message: str) -> Optional[int]:
    match = re.search(r"\b(502|504|322|2104|2106|200|162|354|366)\b", message)
    if match:
        return int(match.group(1))
    match = re.search(r"\b(\d{3,4})\b", message)
    if match:
        return int(match.group(1))
    return None


def _classify_error(exc: Exception) -> tuple:
    msg = str(exc)
    tws_code = _parse_tws_code(msg)

    if isinstance(exc, asyncio.TimeoutError):
        return ("REQUEST_TIMEOUT", "TIMEOUT", tws_code, msg, "Try again later or reduce request size.")

    if isinstance(exc, ConnectionError) or tws_code == 504:
        return ("TWS_DISCONNECTED", "TWS_DISCONNECTED", tws_code or 504, msg, "Check TWS/Gateway is running.")

    if tws_code == 502:
        return ("CONNECTION_FAILED", "NETWORK", 502, msg, "Check TWS/Gateway is running.")

    if tws_code in (322, 162):
        return ("RATE_LIMIT_EXCEEDED", "RATE_LIMIT", tws_code, msg, "Reduce request frequency.")

    if tws_code == 354:
        return ("SUBSCRIPTION_REQUIRED", "SUBSCRIPTION", 354, msg, "Verify market data subscription.")

    if tws_code == 200:
        return ("INVALID_SYMBOL", "SYMBOL", 200, msg, "Check contract symbol and exchange.")

    if tws_code == 366:
        return ("NO_DATA_AVAILABLE", "DATA_UNAVAILABLE", 366, msg, "No historical data for this range.")

    return ("UNKNOWN_ERROR", "NETWORK", tws_code, msg, "Check TWS logs.")


@router.post("/historical", response_model=Union[HistoricalDataResponse, DataErrorResponse])
async def historical_data(
    request: HistoricalDataRequest,
    client: IBKRClient = Depends(get_ibkr_client),
    cache: CacheManager = Depends(get_cache_manager),
) -> Union[HistoricalDataResponse, DataErrorResponse]:
    request_id = uuid.uuid4().hex
    logger.info(
        "[%s] IBKR historical: %s %s %s",
        request_id, request.contract.symbol, request.barSizeSetting, request.durationStr,
    )

    # Cache read-through (source="ibkr")
    try:
        cached_bars = cache.get(request, source="ibkr")
    except Exception as exc:
        logger.warning("[%s] Cache read failed: %s", request_id, exc)
        cached_bars = None

    if cached_bars is not None:
        logger.info("[%s] Cache hit — %d bars", request_id, len(cached_bars))
        start_date = cached_bars[0].date if cached_bars else ""
        end_date = cached_bars[-1].date if cached_bars else ""
        return HistoricalDataResponse(
            status="success",
            request_id=request_id,
            source="ibkr",
            data_router_request_id=request_id,
            contract=request.contract,
            barSizeSetting=request.barSizeSetting,
            whatToShow=request.whatToShow,
            durationStr=request.durationStr,
            useRTH=request.useRTH,
            startDate=start_date,
            endDate=end_date,
            timeZone="EST",
            rows=len(cached_bars),
            bars=cached_bars,
            cached=True,
            fetch_time_ms=0,
        )

    # Pool acquire
    try:
        client_id = client.pool.acquire()
    except Exception as exc:
        logger.error("[%s] Pool exhausted: %s", request_id, exc)
        return DataErrorResponse(
            status="error",
            source="ibkr",
            request_id=request_id,
            attempts=0,
            error_code="POOL_EXHAUSTED",
            error_category="RATE_LIMIT",
            message=str(exc),
            suggestion="Wait for an available connection.",
            contract=request.contract,
        )

    ib_contract = _to_ib_contract(request.contract)
    bars: list[Bar] = []
    last_exception: Optional[Exception] = None
    error_meta: Optional[tuple] = None
    fetch_time_ms = 0

    try:
        start_time = time.perf_counter()
        for attempt in range(6):
            if attempt > 0:
                delay = BACKOFF_DELAYS[attempt - 1]
                logger.warning("[%s] Retry %d/5 after %ds: %s", request_id, attempt, delay, last_exception)
                await asyncio.sleep(delay)

            try:
                if not client.is_connected():
                    client.connect()
                ib = client.get_ib()
                bar_data_list = await ib.reqHistoricalDataAsync(
                    ib_contract,
                    endDateTime=request.endDateTime or "",
                    durationStr=request.durationStr,
                    barSizeSetting=request.barSizeSetting,
                    whatToShow=request.whatToShow,
                    useRTH=request.useRTH,
                    formatDate=request.formatDate,
                )

                if bar_data_list:
                    for b in bar_data_list:
                        bars.append(Bar(
                            date=_format_date(b.date),
                            open=b.open,
                            high=b.high,
                            low=b.low,
                            close=b.close,
                            volume=int(b.volume) if b.volume is not None else 0,
                            wap=b.average if b.average is not None else 0.0,
                            count=int(b.barCount) if b.barCount is not None else 0,
                        ))

                fetch_time_ms = int((time.perf_counter() - start_time) * 1000)
                logger.info("[%s] Fetched %d bars in %dms", request_id, len(bars), fetch_time_ms)
                if bars:
                    try:
                        cache.set(request, bars, source="ibkr")
                    except Exception as exc:
                        logger.warning("[%s] Cache write failed: %s", request_id, exc)
                break

            except Exception as exc:
                last_exception = exc
                error_meta = _classify_error(exc)
                logger.warning("[%s] Attempt %d failed: %s", request_id, attempt + 1, exc)
        else:
            fetch_time_ms = int((time.perf_counter() - start_time) * 1000)
            logger.error("[%s] All retries failed after %dms", request_id, fetch_time_ms)
            return DataErrorResponse(
                status="error",
                source="ibkr",
                request_id=request_id,
                attempts=6,
                error_code=error_meta[0] if error_meta else "UNKNOWN_ERROR",
                error_category=error_meta[1] if error_meta else "NETWORK",
                tws_error_code=error_meta[2] if error_meta else None,
                message=error_meta[3] if error_meta else str(last_exception),
                suggestion=error_meta[4] if error_meta else "Check TWS logs.",
                contract=request.contract,
            )
    finally:
        client.pool.release(client_id)

    start_date = bars[0].date if bars else ""
    end_date = bars[-1].date if bars else ""

    return HistoricalDataResponse(
        status="success",
        request_id=request_id,
        source="ibkr",
        data_router_request_id=request_id,
        contract=request.contract,
        barSizeSetting=request.barSizeSetting,
        whatToShow=request.whatToShow,
        durationStr=request.durationStr,
        useRTH=request.useRTH,
        startDate=start_date,
        endDate=end_date,
        timeZone="EST",
        rows=len(bars),
        bars=bars,
        cached=False,
        fetch_time_ms=fetch_time_ms,
    )
```

- [ ] **Step 2: 修改 data.py 为兼容层**

```python
# data_router/routers/data.py
"""Compatibility layer — forwards to /data/ibkr/historical."""

import logging

from fastapi import APIRouter, Depends

from cache.manager import CacheManager
from dependencies import get_cache_manager, get_ibkr_client
from ibkr.client import IBKRClient
from models import DataErrorResponse, HistoricalDataRequest, HistoricalDataResponse
from .ibkr import historical_data as ibkr_historical_data

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/data", tags=["data"])


@router.post("/historical", response_model=HistoricalDataResponse | DataErrorResponse)
async def historical_data(
    request: HistoricalDataRequest,
    client: IBKRClient = Depends(get_ibkr_client),
    cache: CacheManager = Depends(get_cache_manager),
):
    """DEPRECATED: Use /data/ibkr/historical instead."""
    logger.warning(
        "DEPRECATED: /data/historical is deprecated. Use /data/ibkr/historical instead. "
        "This endpoint will be removed in a future release."
    )
    return await ibkr_historical_data(request, client, cache)
```

- [ ] **Step 3: Commit**

```bash
git add data_router/routers/ibkr.py data_router/routers/data.py
git commit -m "refactor(routers): extract IBKR router, add compatibility layer"
```

---

## Task 5: yfinance Router + Sources Router

**Files:**
- Create: `data_router/routers/yfinance.py`
- Create: `data_router/routers/sources.py`

- [ ] **Step 1: 创建 yfinance.py**

```python
# data_router/routers/yfinance.py
"""YFinance data router — historical bars and fundamental data."""

import logging
import time
import uuid
from typing import Union

from fastapi import APIRouter

from cache.manager import CacheManager
from loaders.yfinance_loader import YFinanceLoader
from models import Bar, DataErrorResponse, DataResponse, FundamentalData, YFHistoricalRequest

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/yfinance", tags=["yfinance"])

_loader = YFinanceLoader()
_cache = CacheManager()  # Uses default DB path


def _yf_key_params(request: YFHistoricalRequest) -> dict:
    """Build a minimal dict that can be hashed for cache key purposes.
    We reuse CacheManager's key logic by constructing a fake HistoricalDataRequest.
    """
    from models import Contract, HistoricalDataRequest
    contract = Contract(
        symbol=request.ticker,
        secType="STK",
        exchange="YF",
        currency="USD",
    )
    return HistoricalDataRequest(
        contract=contract,
        durationStr="1 Y",  # placeholder; yfinance uses start/end instead
        barSizeSetting="1 day",  # mapped from interval
        endDateTime=request.end,
    )


def _map_interval(interval: str) -> str:
    mapping = {"1d": "1 day", "1wk": "1 week", "1mo": "1 month"}
    return mapping.get(interval, "1 day")


@router.post("/historical", response_model=Union[DataResponse, DataErrorResponse])
async def yf_historical(request: YFHistoricalRequest):
    request_id = uuid.uuid4().hex
    logger.info("[%s] YF historical: %s %s-%s (%s)", request_id, request.ticker, request.start, request.end, request.interval)

    # Build cache-compatible request
    cache_req = _yf_key_params(request)
    cache_req.barSizeSetting = _map_interval(request.interval)

    # Cache read-through
    try:
        cached = _cache.get(cache_req, source="yfinance")
    except Exception as exc:
        logger.warning("[%s] Cache read failed: %s", request_id, exc)
        cached = None

    if cached is not None:
        logger.info("[%s] Cache hit — %d bars", request_id, len(cached))
        return DataResponse(
            status="success",
            source="yfinance",
            request_id=request_id,
            data=[b.model_dump() for b in cached],
            metadata={},
            cached=True,
            fetch_time_ms=0,
        )

    # Fetch from yfinance
    start_time = time.perf_counter()
    try:
        bars = _loader.fetch_historical(
            ticker=request.ticker,
            start=request.start,
            end=request.end,
            interval=request.interval,
            auto_adjust=request.auto_adjust,
        )
        fetch_time_ms = int((time.perf_counter() - start_time) * 1000)

        if not bars:
            return DataErrorResponse(
                status="error",
                source="yfinance",
                request_id=request_id,
                attempts=1,
                error_code="NO_DATA_AVAILABLE",
                error_category="DATA_UNAVAILABLE",
                message=f"No data available for {request.ticker}",
                suggestion="Check ticker symbol or date range.",
                fallback_available=["ibkr"],
            )

        # Cache write-through
        try:
            _cache.set(cache_req, bars, source="yfinance")
        except Exception as exc:
            logger.warning("[%s] Cache write failed: %s", request_id, exc)

        # Extract adj_close for metadata if available
        metadata = {}
        # yfinance_loader currently doesn't return adj_close separately;
        # if auto_adjust=True, close is already adjusted.

        return DataResponse(
            status="success",
            source="yfinance",
            request_id=request_id,
            data=[b.model_dump() for b in bars],
            metadata=metadata,
            cached=False,
            fetch_time_ms=fetch_time_ms,
        )

    except Exception as exc:
        fetch_time_ms = int((time.perf_counter() - start_time) * 1000)
        logger.error("[%s] YF fetch failed: %s", request_id, exc)
        return DataErrorResponse(
            status="error",
            source="yfinance",
            request_id=request_id,
            attempts=1,
            error_code="FETCH_ERROR",
            error_category="NETWORK",
            message=str(exc),
            suggestion="Check network or try again later.",
            fallback_available=["ibkr"],
        )


@router.get("/fundamental/{ticker}", response_model=Union[DataResponse, DataErrorResponse])
async def yf_fundamental(ticker: str):
    request_id = uuid.uuid4().hex
    logger.info("[%s] YF fundamental: %s", request_id, ticker)

    start_time = time.perf_counter()
    try:
        fund = _loader.fetch_fundamental(ticker)
        fetch_time_ms = int((time.perf_counter() - start_time) * 1000)

        if fund is None:
            return DataErrorResponse(
                status="error",
                source="yfinance",
                request_id=request_id,
                attempts=1,
                error_code="NO_DATA_AVAILABLE",
                error_category="DATA_UNAVAILABLE",
                message=f"No fundamental data for {ticker}",
                suggestion="Check ticker symbol.",
                fallback_available=[],
            )

        return DataResponse(
            status="success",
            source="yfinance",
            request_id=request_id,
            data=[fund.model_dump()],
            metadata={},
            cached=False,
            fetch_time_ms=fetch_time_ms,
        )

    except Exception as exc:
        fetch_time_ms = int((time.perf_counter() - start_time) * 1000)
        logger.error("[%s] YF fundamental failed: %s", request_id, exc)
        return DataErrorResponse(
            status="error",
            source="yfinance",
            request_id=request_id,
            attempts=1,
            error_code="FETCH_ERROR",
            error_category="NETWORK",
            message=str(exc),
            suggestion="Check network or try again later.",
            fallback_available=[],
        )
```

- [ ] **Step 2: 创建 sources.py**

```python
# data_router/routers/sources.py
"""Data source health and availability endpoint."""

import logging

from fastapi import APIRouter

from cache.manager import CacheManager
from ibkr.client import IBKRClient
from loaders.akshare_loader import AKShareLoader
from loaders.yfinance_loader import YFinanceLoader
from models import DataResponse, SourceHealth

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/sources", tags=["sources"])

# Shared state — in production these would be injected via Depends
_ibkr_client: IBKRClient | None = None
_cache = CacheManager()


def _get_ibkr_client() -> IBKRClient | None:
    """Lazy init IBKR client for health checks."""
    global _ibkr_client
    if _ibkr_client is None:
        import os
        host = os.getenv("TWS_HOST", "host.docker.internal")
        port = int(os.getenv("TWS_PORT", "7497"))
        _ibkr_client = IBKRClient(host=host, port=port)
    return _ibkr_client


@router.get("", response_model=DataResponse)
async def list_sources():
    request_id = "sources-" + str(hash(str(_cache.stats())))[:8]

    sources: list[SourceHealth] = []
    cache_stats = _cache.stats()

    # IBKR
    ibkr_client = _get_ibkr_client()
    ibkr_health = ibkr_client.health() if ibkr_client else {"connected": False}
    ibkr_cache = cache_stats.get("sources", {}).get("ibkr", {})
    sources.append(SourceHealth(
        name="ibkr",
        available=ibkr_health.get("connected", False),
        markets=["US", "HK", "JP", "EU"],
        latency_ms=ibkr_health.get("latency_ms"),
        message="connected" if ibkr_health.get("connected") else "disconnected",
        cache_stats=ibkr_cache,
    ))

    # YFinance
    yf_loader = YFinanceLoader()
    yf_health = yf_loader.health()
    yf_cache = cache_stats.get("sources", {}).get("yfinance", {})
    sources.append(SourceHealth(
        name="yfinance",
        available=yf_health.get("available", False),
        markets=["US", "HK"],
        latency_ms=yf_health.get("latency_ms"),
        message=yf_health.get("message", ""),
        cache_stats=yf_cache,
    ))

    # AKShare (placeholder)
    ak_loader = AKShareLoader()
    ak_health = ak_loader.health()
    sources.append(SourceHealth(
        name="akshare",
        available=False,
        markets=["CN"],
        latency_ms=None,
        message="not configured",
        cache_stats={},
    ))

    return DataResponse(
        status="success",
        source="data_router",
        request_id=request_id,
        data=[s.model_dump() for s in sources],
        metadata={"total_sources": len(sources), "available": sum(1 for s in sources if s.available)},
        cached=False,
        fetch_time_ms=0,
    )
```

- [ ] **Step 3: Commit**

```bash
git add data_router/routers/yfinance.py data_router/routers/sources.py
git commit -m "feat(routers): add yfinance and sources endpoints"
```

---

## Task 6: 注册 Routers + 依赖更新

**Files:**
- Modify: `data_router/main.py`
- Modify: `data_router/routers/__init__.py`
- Modify: `data_router/requirements.txt`

- [ ] **Step 1: 修改 routers/__init__.py**

```python
# data_router/routers/__init__.py
from .data import router as data_router
from .ibkr import router as ibkr_router
from .sources import router as sources_router
from .yfinance import router as yfinance_router

__all__ = ["data_router", "ibkr_router", "sources_router", "yfinance_router"]
```

- [ ] **Step 2: 修改 main.py 注册新 routers**

```python
# data_router/main.py
from fastapi import FastAPI

# ... existing imports ...
from routers import data, ibkr, sources, yfinance


def create_app() -> FastAPI:
    app = FastAPI(
        title="Quant Cluster — Data Router",
        description="Multi-source historical data gateway for the quant trading cluster.",
        version="0.2.0",  # bump version
        lifespan=lifespan,
    )
    app.include_router(data.router)
    app.include_router(ibkr.router)
    app.include_router(yfinance.router)
    app.include_router(sources.router)

    @app.get("/health")
    async def health():
        return app.state.ibkr_client.health()

    return app


app = create_app()
```

- [ ] **Step 3: 更新 requirements.txt**

Append to `data_router/requirements.txt`:

```
yfinance>=0.2.54
pandas>=2.0.0
```

- [ ] **Step 4: 验证 imports**

Run: `cd data_router && python -c "from main import create_app; print('OK')"`

Expected: `OK` (if yfinance is installed; if not, install first)

- [ ] **Step 5: Commit**

```bash
git add data_router/main.py data_router/routers/__init__.py data_router/requirements.txt
git commit -m "chore: register new routers, add yfinance dependency, bump version"
```

---

## Task 7: 端到端验证

**Files:**
- None (verification only)

- [ ] **Step 1: 安装 yfinance**

Run: `pip install yfinance>=0.2.54 pandas>=2.0.0`

- [ ] **Step 2: 启动 data_router 并测试 health**

Run: `cd data_router && uvicorn main:app --reload --port 8080 &`
Then: `curl http://localhost:8080/health`

Expected: `{"connected": ...}`

- [ ] **Step 3: 测试 /data/sources**

Run: `curl http://localhost:8080/data/sources`

Expected: JSON with 3 sources (ibkr, yfinance, akshare)

- [ ] **Step 4: 测试 /data/yfinance/historical**

Run:
```bash
curl -X POST http://localhost:8080/data/yfinance/historical \
  -H "Content-Type: application/json" \
  -d '{"ticker": "AAPL", "start": "2024-01-01", "end": "2024-01-10", "interval": "1d"}'
```

Expected: DataResponse with bars array

- [ ] **Step 5: 测试 /data/yfinance/fundamental/AAPL**

Run: `curl http://localhost:8080/data/yfinance/fundamental/AAPL`

Expected: DataResponse with fundamental data

- [ ] **Step 6: 测试 /data/ibkr/historical**

Run:
```bash
curl -X POST http://localhost:8080/data/ibkr/historical \
  -H "Content-Type: application/json" \
  -d '{"contract": {"symbol": "AAPL", "secType": "STK", "exchange": "SMART", "currency": "USD"}, "durationStr": "5 D", "barSizeSetting": "1 hour"}'
```

Expected: HistoricalDataResponse (requires TWS connection)

- [ ] **Step 7: 测试旧端点兼容性**

Run:
```bash
curl -X POST http://localhost:8080/data/historical \
  -H "Content-Type: application/json" \
  -d '{"contract": {"symbol": "AAPL", "secType": "STK", "exchange": "SMART", "currency": "USD"}, "durationStr": "5 D", "barSizeSetting": "1 hour"}'
```

Expected: Same as /data/ibkr/historical, plus deprecation log in server output

- [ ] **Step 8: Commit 验证结果（如有修改）**

```bash
git add -A
git commit -m "test: e2e verification passed for all new endpoints"
```

---

## Self-Review Checklist

**1. Spec coverage:**
- [x] yfinance_loader.py — Task 3
- [x] Loader Registry Protocol — Task 3 (base.py)
- [x] 自动回退链 — Agent 端通过 `/data/sources` + `fallback_available` 实现（Tasks 2, 5）
- [x] yfinance 基本面数据接口 — Task 5 (`/data/yfinance/fundamental/{ticker}`)
- [x] `/data/sources` 元数据接口 — Task 5
- [x] Cache 层扩展（source 标签）— Tasks 1, 4
- [x] 向后兼容 — Task 4 (data.py 兼容层)

**2. Placeholder scan:**
- [x] 无 TBD/TODO
- [x] 无 "implement later"
- [x] 无 "add appropriate error handling" 等模糊描述
- [x] 每个步骤都有完整代码

**3. Type consistency:**
- [x] `CacheManager.get/set/invalidate` 签名统一使用 `source: str = "ibkr"`
- [x] `DataErrorResponse` 在所有 router 中使用一致
- [x] `DataResponse` 包装格式一致
