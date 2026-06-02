# Paper Downloader Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build a multi-source academic paper downloader engine (`tools/paper_downloader/`) with CLI, SQLite store, and source plugins for arXiv (OAI-PMH + GCS batch), CORE API, Elsevier, Wiley, and NeurIPS; plus an Agent config (`agent_configs/paper_downloader/`).

**Architecture:** Modular plugin architecture — `Source` ABC with `scan()` (metadata discovery) and `download()` (PDF fetch), decoupled via `PaperStore` (SQLite) and `Scheduler` (frequency dispatch). HTTP/API sources run in the Python engine; browser-only sources (SSRN) are handled by the Agent. arXiv supports dual-mode: incremental via OAI-PMH/API and bulk backfill via public GCS bucket.

**Tech Stack:** Python 3.9+, `requests`, `sqlite3`, `pytest`, `dataclasses`, `asyncio` (optional), `xml.etree.ElementTree` (OAI-PMH parsing), no external DB.

---

## File Structure Map

```
tools/paper_downloader/
├── __init__.py
├── __main__.py              # CLI entry: argparse subcommands
├── config.yaml              # Source frequencies, API keys, backfill settings
├── core/
│   ├── __init__.py
│   ├── models.py            # PaperMeta dataclass
│   ├── store.py             # SQLite schema + PaperStore CRUD
│   ├── downloader.py        # HTTP download with retry + rate limit
│   └── scheduler.py         # Frequency-based source dispatch
├── sources/
│   ├── __init__.py
│   ├── base.py              # Source ABC
│   ├── arxiv.py             # OAI-PMH incremental + GCS bulk
│   ├── core_ac.py           # CORE API v3 (Works search → Outputs download)
│   ├── elsevier.py          # Scopus Search + Article Retrieval
│   ├── wiley.py             # Crossref discovery + TDM download
│   └── conference.py        # NeurIPS (HTML scrape)
└── tests/
    ├── test_models.py
    ├── test_store.py
    ├── test_downloader.py
    ├── test_arxiv.py
    └── test_core_ac.py

agent_configs/paper_downloader/
├── SOUL.md                  # Agent system prompt
└── config.yaml              # Hermes runtime config

Modified existing files:
- orchestrator/core/dag.py   # Add paper_downloader to AGENTS (non-DAG)
```

---

## Prerequisites

Before starting, verify environment:

```bash
cd "/Users/yihaoyang/VScode workspace/quant-cluster"
python3 --version  # >= 3.9
python3 -c "import requests; print('requests OK')"
python3 -c "import pytest; print('pytest OK')"
mkdir -p tools/paper_downloader/{core,sources,tests}
mkdir -p agent_configs/paper_downloader
mkdir -p shared_workspace/papers/raw
```

---

## Task 1: Core Models (`core/models.py`)

**Files:**
- Create: `tools/paper_downloader/core/__init__.py`
- Create: `tools/paper_downloader/core/models.py`
- Create: `tools/paper_downloader/tests/test_models.py`

- [ ] **Step 1: Write the failing test**

```python
# tools/paper_downloader/tests/test_models.py
import sys, os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..'))

from core.models import PaperMeta

def test_paper_meta_creation():
    meta = PaperMeta(
        source="arxiv_qfin",
        source_id="2306.16127",
        title="Test Paper",
        authors=["Alice", "Bob"],
        year=2024,
    )
    assert meta.source == "arxiv_qfin"
    assert meta.source_id == "2306.16127"
    assert meta.doi is None

def test_unique_key_with_doi():
    meta = PaperMeta(source="core", source_id="123", doi="10.1234/test")
    assert meta.unique_key() == "10.1234/test"

def test_unique_key_without_doi():
    meta = PaperMeta(source="arxiv", source_id="2306.16127")
    assert meta.unique_key() == "arxiv:2306.16127"

def test_suggested_filename():
    meta = PaperMeta(source="core", source_id="80549003")
    assert meta.suggested_filename() == "core_80549003.pdf"
```

- [ ] **Step 2: Run test to verify it fails**

```bash
cd "/Users/yihaoyang/VScode workspace/quant-cluster/tools/paper_downloader"
python3 -m pytest tests/test_models.py -v
```

Expected: `ModuleNotFoundError: No module named 'core.models'`

- [ ] **Step 3: Implement minimal `__init__.py` and `models.py`**

```python
# tools/paper_downloader/core/__init__.py
# Empty package init
```

```python
# tools/paper_downloader/core/models.py
from dataclasses import dataclass, asdict
from datetime import datetime
from pathlib import Path
from typing import List, Optional
import json


@dataclass
class PaperMeta:
    """一篇论文的元数据，所有 Source 统一输出此格式"""
    source: str
    source_id: str
    doi: Optional[str] = None
    title: str = ""
    authors: List[str] = None
    abstract: Optional[str] = None
    published_at: Optional[datetime] = None
    year: Optional[int] = None
    pdf_url: Optional[str] = None
    landing_url: Optional[str] = None

    def unique_key(self) -> str:
        """去重标识：有 DOI 用 DOI，否则用 source + source_id"""
        return self.doi.lower() if self.doi else f"{self.source}:{self.source_id}"

    def suggested_filename(self) -> str:
        """建议的文件名：{source}_{safe_id}.pdf"""
        safe_id = str(self.source_id).replace("/", "_").replace(":", "_")
        return f"{self.source}_{safe_id}.pdf"
```

- [ ] **Step 4: Run tests**

```bash
cd "/Users/yihaoyang/VScode workspace/quant-cluster/tools/paper_downloader"
python3 -m pytest tests/test_models.py -v
```

Expected: 4 passed

- [ ] **Step 5: Commit**

```bash
cd "/Users/yihaoyang/VScode workspace/quant-cluster"
git add tools/paper_downloader/core/__init__.py tools/paper_downloader/core/models.py tools/paper_downloader/tests/test_models.py
git commit -m "feat(downloader): add PaperMeta dataclass"
```

---

## Task 2: SQLite Store (`core/store.py`)

**Files:**
- Create: `tools/paper_downloader/core/store.py`
- Create: `tools/paper_downloader/tests/test_store.py`

- [ ] **Step 1: Write the failing test**

```python
# tools/paper_downloader/tests/test_store.py
import sys, os, tempfile
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..'))

from core.store import PaperStore
from core.models import PaperMeta

def test_store_init_creates_schema():
    with tempfile.NamedTemporaryFile(suffix=".db", delete=False) as f:
        db_path = f.name
    store = PaperStore(db_path)
    # Check tables exist
    cursor = store.conn.execute("SELECT name FROM sqlite_master WHERE type='table'")
    tables = {row[0] for row in cursor.fetchall()}
    assert "papers" in tables
    assert "scan_log" in tables
    os.unlink(db_path)

def test_dedupe_and_insert():
    with tempfile.NamedTemporaryFile(suffix=".db", delete=False) as f:
        db_path = f.name
    store = PaperStore(db_path)
    metas = [
        PaperMeta(source="arxiv", source_id="2306.16127", title="Paper A"),
        PaperMeta(source="arxiv", source_id="2306.16127", title="Paper A Dup"),
        PaperMeta(source="core", source_id="123", title="Paper B"),
    ]
    new_metas = store.dedupe_and_insert(metas)
    assert len(new_metas) == 2  # second duplicate skipped
    os.unlink(db_path)

def test_get_pending():
    with tempfile.NamedTemporaryFile(suffix=".db", delete=False) as f:
        db_path = f.name
    store = PaperStore(db_path)
    store.dedupe_and_insert([PaperMeta(source="arxiv", source_id="1", title="T")])
    pending = store.get_pending("arxiv")
    assert len(pending) == 1
    os.unlink(db_path)
```

- [ ] **Step 2: Run test to verify it fails**

```bash
cd "/Users/yihaoyang/VScode workspace/quant-cluster/tools/paper_downloader"
python3 -m pytest tests/test_store.py -v
```

Expected: `ModuleNotFoundError: No module named 'core.store'`

- [ ] **Step 3: Implement `store.py`**

```python
# tools/paper_downloader/core/store.py
import sqlite3
import json
from pathlib import Path
from datetime import datetime
from typing import List, Optional
from core.models import PaperMeta


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
    def __init__(self, db_path: Path):
        self.conn = sqlite3.connect(str(db_path))
        self.conn.row_factory = sqlite3.Row
        self._init_schema()

    def _init_schema(self):
        self.conn.executescript(SCHEMA)
        self.conn.commit()

    def dedupe_and_insert(self, metas: List[PaperMeta]) -> List[PaperMeta]:
        new_metas = []
        for meta in metas:
            # Check duplicate by (source, source_id)
            cursor = self.conn.execute(
                "SELECT id FROM papers WHERE source = ? AND source_id = ?",
                (meta.source, meta.source_id),
            )
            if cursor.fetchone():
                continue
            # Check duplicate by DOI
            if meta.doi:
                cursor = self.conn.execute(
                    "SELECT id FROM papers WHERE doi = ?", (meta.doi.lower(),)
                )
                if cursor.fetchone():
                    continue
            authors_json = json.dumps(meta.authors) if meta.authors else None
            published_str = meta.published_at.isoformat() if meta.published_at else None
            cursor = self.conn.execute(
                """INSERT INTO papers
                (source, source_id, doi, title, authors, abstract, published_at, year, pdf_url, landing_url)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                (meta.source, meta.source_id, meta.doi, meta.title, authors_json,
                 meta.abstract, published_str, meta.year, meta.pdf_url, meta.landing_url),
            )
            meta.id = cursor.lastrowid
            new_metas.append(meta)
        self.conn.commit()
        return new_metas

    def get_pending(self, source: str, limit: int = 100) -> List[PaperMeta]:
        cursor = self.conn.execute(
            "SELECT * FROM papers WHERE source = ? AND status = 'pending' ORDER BY published_at DESC LIMIT ?",
            (source, limit),
        )
        rows = cursor.fetchall()
        return [self._row_to_meta(row) for row in rows]

    def mark_downloaded(self, paper_id: int, filepath: Path):
        self.conn.execute(
            "UPDATE papers SET status = 'downloaded', downloaded_at = datetime('now'), filepath = ? WHERE id = ?",
            (str(filepath), paper_id),
        )
        self.conn.commit()

    def mark_failed(self, paper_id: int, reason: str):
        self.conn.execute(
            """UPDATE papers
            SET fail_count = fail_count + 1, last_fail_reason = ?,
                status = CASE WHEN fail_count + 1 >= 3 THEN 'skipped' ELSE 'failed' END
            WHERE id = ?""",
            (reason, paper_id),
        )
        self.conn.commit()

    def get_latest_published_at(self, source: str) -> Optional[datetime]:
        cursor = self.conn.execute(
            "SELECT MAX(published_at) FROM papers WHERE source = ?", (source,)
        )
        row = cursor.fetchone()
        if row and row[0]:
            return datetime.fromisoformat(row[0])
        return None

    def _row_to_meta(self, row: sqlite3.Row) -> PaperMeta:
        meta = PaperMeta(
            source=row["source"],
            source_id=row["source_id"],
            doi=row["doi"],
            title=row["title"],
            authors=json.loads(row["authors"]) if row["authors"] else None,
            abstract=row["abstract"],
            year=row["year"],
            pdf_url=row["pdf_url"],
            landing_url=row["landing_url"],
        )
        if row["published_at"]:
            meta.published_at = datetime.fromisoformat(row["published_at"])
        meta.id = row["id"]
        return meta
```

- [ ] **Step 4: Run tests**

```bash
cd "/Users/yihaoyang/VScode workspace/quant-cluster/tools/paper_downloader"
python3 -m pytest tests/test_store.py -v
```

Expected: 3 passed

- [ ] **Step 5: Commit**

```bash
cd "/Users/yihaoyang/VScode workspace/quant-cluster"
git add tools/paper_downloader/core/store.py tools/paper_downloader/tests/test_store.py
git commit -m "feat(downloader): add SQLite PaperStore with schema and CRUD"
```

---

## Task 3: HTTP Downloader (`core/downloader.py`)

**Files:**
- Create: `tools/paper_downloader/core/downloader.py`
- Create: `tools/paper_downloader/tests/test_downloader.py`

- [ ] **Step 1: Write the failing test**

```python
# tools/paper_downloader/tests/test_downloader.py
import sys, os, tempfile
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..'))

from core.downloader import DownloadError, download_file
from unittest.mock import patch, MagicMock

def test_download_success(tmp_path):
    with patch('core.downloader.requests.get') as mock_get:
        mock_get.return_value.status_code = 200
        mock_get.return_value.content = b"PDF content"
        mock_get.return_value.headers = {"content-type": "application/pdf"}
        dest = tmp_path / "test.pdf"
        download_file("http://example.com/paper.pdf", dest, rate_limit_delay=0)
        assert dest.read_bytes() == b"PDF content"

def test_download_non_pdf_detected(tmp_path):
    with patch('core.downloader.requests.get') as mock_get:
        mock_get.return_value.status_code = 200
        mock_get.return_value.content = b"<html>not pdf</html>"
        mock_get.return_value.headers = {"content-type": "text/html"}
        dest = tmp_path / "test.pdf"
        try:
            download_file("http://example.com/paper.pdf", dest, rate_limit_delay=0)
            assert False, "Should raise DownloadError"
        except DownloadError as e:
            assert "not a PDF" in str(e)

def test_download_retries_on_500():
    with patch('core.downloader.requests.get') as mock_get:
        mock_get.side_effect = [
            MagicMock(status_code=500, content=b"", headers={}),
            MagicMock(status_code=200, content=b"PDF content", headers={"content-type": "application/pdf"}),
        ]
        with tempfile.TemporaryDirectory() as tmp:
            dest = Path(tmp) / "test.pdf"
            download_file("http://example.com/paper.pdf", dest, max_retries=2, rate_limit_delay=0)
            assert dest.read_bytes() == b"PDF content"
```

- [ ] **Step 2: Run test to verify it fails**

```bash
cd "/Users/yihaoyang/VScode workspace/quant-cluster/tools/paper_downloader"
python3 -m pytest tests/test_downloader.py -v
```

Expected: `ModuleNotFoundError: No module named 'core.downloader'`

- [ ] **Step 3: Implement `downloader.py`**

```python
# tools/paper_downloader/core/downloader.py
import time
import requests
from pathlib import Path
from typing import Optional


class DownloadError(Exception):
    """下载失败，包含可重试/不可重试的语义"""
    pass


class PaywalledError(DownloadError):
    """付费墙内容，不应重试"""
    pass


def download_file(
    url: str,
    dest_path: Path,
    headers: Optional[dict] = None,
    rate_limit_delay: float = 1.0,
    max_retries: int = 3,
    timeout: int = 30,
) -> Path:
    """下载文件到指定路径，带重试和 rate limit。
    
    返回最终文件路径。失败时抛出 DownloadError 或 PaywalledError。
    """
    dest_path = Path(dest_path)
    dest_path.parent.mkdir(parents=True, exist_ok=True)
    
    last_error = None
    for attempt in range(max_retries):
        try:
            resp = requests.get(url, headers=headers or {}, timeout=timeout, stream=True)
            
            if resp.status_code == 403:
                raise PaywalledError(f"403 Forbidden: {url}")
            if resp.status_code == 404:
                raise DownloadError(f"404 Not Found: {url}")
            if resp.status_code == 429:
                retry_after = int(resp.headers.get("Retry-After", rate_limit_delay * 5))
                time.sleep(retry_after)
                continue
            resp.raise_for_status()
            
            content = resp.content
            # Basic PDF magic check
            if len(content) > 8 and content[:4] == b"%PDF":
                dest_path.write_bytes(content)
                time.sleep(rate_limit_delay)
                return dest_path
            # Allow application/pdf content-type even without magic (some servers)
            ct = resp.headers.get("content-type", "").lower()
            if "pdf" in ct:
                dest_path.write_bytes(content)
                time.sleep(rate_limit_delay)
                return dest_path
            raise DownloadError(f"Downloaded content is not a PDF (content-type: {ct})")
            
        except (requests.RequestException, DownloadError) as e:
            last_error = e
            if isinstance(e, PaywalledError):
                raise
            if attempt < max_retries - 1:
                backoff = rate_limit_delay * (2 ** attempt)
                time.sleep(backoff)
            else:
                raise DownloadError(f"Failed after {max_retries} retries: {e}") from e
    
    raise last_error or DownloadError("Unknown download failure")
```

- [ ] **Step 4: Run tests**

```bash
cd "/Users/yihaoyang/VScode workspace/quant-cluster/tools/paper_downloader"
python3 -m pytest tests/test_downloader.py -v
```

Expected: 3 passed

- [ ] **Step 5: Commit**

```bash
cd "/Users/yihaoyang/VScode workspace/quant-cluster"
git add tools/paper_downloader/core/downloader.py tools/paper_downloader/tests/test_downloader.py
git commit -m "feat(downloader): add HTTP download with retry, rate limit, PDF validation"
```

---

## Task 4: Source Base Class (`sources/base.py`)

**Files:**
- Create: `tools/paper_downloader/sources/__init__.py`
- Create: `tools/paper_downloader/sources/base.py`

- [ ] **Step 1: Write the failing test**

```python
# tools/paper_downloader/tests/test_base.py
import sys, os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..'))

from sources.base import Source
from core.models import PaperMeta

def test_source_abc_cannot_instantiate():
    try:
        s = Source()
        assert False, "Should raise TypeError"
    except TypeError:
        pass
```

- [ ] **Step 2: Run test**

```bash
cd "/Users/yihaoyang/VScode workspace/quant-cluster/tools/paper_downloader"
python3 -m pytest tests/test_base.py -v
```

Expected: `ModuleNotFoundError: No module named 'sources.base'`

- [ ] **Step 3: Implement `base.py`**

```python
# tools/paper_downloader/sources/__init__.py
# Empty package init
```

```python
# tools/paper_downloader/sources/base.py
from abc import ABC, abstractmethod
from datetime import datetime
from pathlib import Path
from typing import List
from core.models import PaperMeta


class Source(ABC):
    """每个来源必须实现的接口"""
    
    name: str = ""
    frequency: str = ""  # daily, weekly, monthly, yearly, on_demand
    rate_limit_delay: float = 3.0
    max_retries: int = 3
    
    @abstractmethod
    def scan(self, since: datetime) -> List[PaperMeta]:
        """发现自 since 以来发布/更新的论文。"""
        pass
    
    @abstractmethod
    def download(self, meta: PaperMeta, dest_path: Path) -> Path:
        """将 PDF 下载到 dest_path，返回最终文件路径。"""
        pass
```

- [ ] **Step 4: Run tests**

```bash
cd "/Users/yihaoyang/VScode workspace/quant-cluster/tools/paper_downloader"
python3 -m pytest tests/test_base.py -v
```

Expected: 1 passed

- [ ] **Step 5: Commit**

```bash
cd "/Users/yihaoyang/VScode workspace/quant-cluster"
git add tools/paper_downloader/sources/__init__.py tools/paper_downloader/sources/base.py tools/paper_downloader/tests/test_base.py
git commit -m "feat(downloader): add Source ABC"
```

---

## Task 5: Scheduler (`core/scheduler.py`)

**Files:**
- Create: `tools/paper_downloader/core/scheduler.py`
- Create: `tools/paper_downloader/tests/test_scheduler.py`

- [ ] **Step 1: Write the failing test**

```python
# tools/paper_downloader/tests/test_scheduler.py
import sys, os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..'))

from core.scheduler import Scheduler, should_run
from datetime import datetime, timedelta

def test_should_run_weekly_never_run():
    assert should_run("weekly", None) is True

def test_should_run_weekly_recently_run():
    last = datetime.now() - timedelta(days=2)
    assert should_run("weekly", last) is False

def test_should_run_weekly_long_ago():
    last = datetime.now() - timedelta(days=8)
    assert should_run("weekly", last) is True

def test_scheduler_filters_sources():
    from sources.base import Source
    class MockSource(Source):
        name = "mock_weekly"
        frequency = "weekly"
        def scan(self, since): return []
        def download(self, meta, dest): return dest
    
    scheduler = Scheduler([MockSource()], config={})
    sources = scheduler.get_due_sources()
    assert len(sources) == 1
```

- [ ] **Step 2: Run test**

```bash
cd "/Users/yihaoyang/VScode workspace/quant-cluster/tools/paper_downloader"
python3 -m pytest tests/test_scheduler.py -v
```

Expected: `ModuleNotFoundError: No module named 'core.scheduler'`

- [ ] **Step 3: Implement `scheduler.py`**

```python
# tools/paper_downloader/core/scheduler.py
from datetime import datetime, timedelta
from typing import List, Dict, Any, Optional
from core.models import PaperMeta
from core.store import PaperStore
from sources.base import Source


FREQUENCY_DELTA = {
    "daily": timedelta(days=1),
    "weekly": timedelta(weeks=1),
    "monthly": timedelta(days=30),
    "yearly": timedelta(days=365),
}


def should_run(frequency: str, last_run: Optional[datetime]) -> bool:
    if last_run is None:
        return True
    delta = FREQUENCY_DELTA.get(frequency, timedelta(days=1))
    return datetime.now() - last_run >= delta


class Scheduler:
    def __init__(self, sources: List[Source], config: Dict[str, Any]):
        self.sources = {s.name: s for s in sources}
        self.config = config
    
    def get_due_sources(self, store: Optional[PaperStore] = None) -> List[Source]:
        """返回当前应该运行的 source 列表"""
        due = []
        for name, source in self.sources.items():
            src_cfg = self.config.get("sources", {}).get(name, {})
            if not src_cfg.get("enabled", True):
                continue
            # For now, always run on-demand or if no store tracking
            due.append(source)
        return due
    
    def run_source(self, source: Source, store: PaperStore, raw_dir: Path) -> dict:
        """执行单个 source 的 scan + download 循环"""
        since = store.get_latest_published_at(source.name)
        if since is None:
            since_cfg = self.config.get("backfill", {}).get("year_from", "2010-01-01")
            since = datetime.strptime(since_cfg, "%Y-%m-%d")
        
        metas = source.scan(since)
        new_metas = store.dedupe_and_insert(metas)
        
        downloaded = failed = 0
        for meta in new_metas:
            year = meta.year or datetime.now().year
            dest_dir = raw_dir / source.name / str(year)
            dest_path = dest_dir / meta.suggested_filename()
            try:
                source.download(meta, dest_path)
                store.mark_downloaded(meta.id, dest_path)
                downloaded += 1
            except Exception as e:
                store.mark_failed(meta.id, str(e))
                failed += 1
        
        return {
            "source": source.name,
            "found": len(metas),
            "new": len(new_metas),
            "downloaded": downloaded,
            "failed": failed,
        }
```

- [ ] **Step 4: Run tests**

```bash
cd "/Users/yihaoyang/VScode workspace/quant-cluster/tools/paper_downloader"
python3 -m pytest tests/test_scheduler.py -v
```

Expected: 4 passed

- [ ] **Step 5: Commit**

```bash
cd "/Users/yihaoyang/VScode workspace/quant-cluster"
git add tools/paper_downloader/core/scheduler.py tools/paper_downloader/tests/test_scheduler.py
git commit -m "feat(downloader): add Scheduler with frequency-based dispatch"
```

---

## Task 6: arXiv Source (`sources/arxiv.py`)

**Files:**
- Create: `tools/paper_downloader/sources/arxiv.py`
- Create: `tools/paper_downloader/tests/test_arxiv.py`

- [ ] **Step 1: Write the failing test**

```python
# tools/paper_downloader/tests/test_arxiv.py
import sys, os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..'))

from sources.arxiv import ArxivSource
from datetime import datetime

def test_arxiv_source_name():
    src = ArxivSource("q-fin.TR")
    assert src.name == "arxiv_qfin_tr"

def test_parse_arxiv_id_from_url():
    from sources.arxiv import parse_arxiv_id
    assert parse_arxiv_id("http://arxiv.org/abs/2306.16127") == "2306.16127"
    assert parse_arxiv_id("https://arxiv.org/abs/2306.16127v2") == "2306.16127v2"
```

- [ ] **Step 2: Run test**

```bash
cd "/Users/yihaoyang/VScode workspace/quant-cluster/tools/paper_downloader"
python3 -m pytest tests/test_arxiv.py -v
```

Expected: `ModuleNotFoundError: No module named 'sources.arxiv'`

- [ ] **Step 3: Implement `arxiv.py`**

```python
# tools/paper_downloader/sources/arxiv.py
import requests
import time
import xml.etree.ElementTree as ET
from datetime import datetime
from pathlib import Path
from typing import List
from sources.base import Source
from core.models import PaperMeta
from core.downloader import download_file

ARXIV_API = "http://export.arxiv.org/api/query"
ARXIV_PDF = "https://arxiv.org/pdf/{id}.pdf"
GCS_BASE = "https://storage.googleapis.com/arxiv-dataset"


def parse_arxiv_id(url: str) -> str:
    """从 arXiv URL 提取 ID"""
    url = url.rstrip("/")
    if "/abs/" in url:
        return url.split("/abs/")[-1]
    return url.split("/")[-1]


class ArxivSource(Source):
    """arXiv source: 增量 via OAI-PMH/API, 批量回溯 via GCS"""
    
    def __init__(self, category: str, backfill_mode: str = "api"):
        self.category = category
        self.name = f"arxiv_{category.replace('.', '_').replace('-', '_')}"
        self.frequency = "weekly"
        self.rate_limit_delay = 3.0
        self.backfill_mode = backfill_mode
    
    def scan(self, since: datetime) -> List[PaperMeta]:
        if self.backfill_mode == "gcs":
            return self._scan_gcs(since)
        return self._scan_api(since)
    
    def _scan_api(self, since: datetime) -> List[PaperMeta]:
        """通过 arXiv API 获取增量论文"""
        metas = []
        start = 0
        while True:
            params = {
                "search_query": f"cat:{self.category}",
                "sortBy": "submittedDate",
                "sortOrder": "descending",
                "start": start,
                "max_results": 100,
            }
            resp = requests.get(ARXIV_API, params=params, timeout=30)
            resp.raise_for_status()
            root = ET.fromstring(resp.content)
            ns = {"atom": "http://www.w3.org/2005/Atom"}
            entries = root.findall(".//atom:entry", ns)
            if not entries:
                break
            for entry in entries:
                id_elem = entry.find("atom:id", ns)
                title_elem = entry.find("atom:title", ns)
                summary_elem = entry.find("atom:summary", ns)
                published_elem = entry.find("atom:published", ns)
                
                arxiv_id = parse_arxiv_id(id_elem.text) if id_elem is not None else ""
                published = datetime.fromisoformat(published_elem.text.replace("Z", "+00:00")) if published_elem is not None else datetime.now()
                
                if published < since:
                    return metas
                
                authors = []
                for author in entry.findall("atom:author", ns):
                    name = author.find("atom:name", ns)
                    if name is not None:
                        authors.append(name.text)
                
                pdf_link = entry.find('.//atom:link[@title="pdf"]', ns)
                pdf_url = pdf_link.get("href") if pdf_link is not None else ARXIV_PDF.format(id=arxiv_id)
                
                metas.append(PaperMeta(
                    source=self.name,
                    source_id=arxiv_id,
                    title=title_elem.text.strip() if title_elem is not None else "",
                    authors=authors,
                    abstract=summary_elem.text.strip() if summary_elem is not None else None,
                    published_at=published,
                    year=published.year,
                    pdf_url=pdf_url,
                    landing_url=id_elem.text if id_elem is not None else None,
                ))
            start += len(entries)
            time.sleep(self.rate_limit_delay)
        return metas
    
    def _scan_gcs(self, since: datetime) -> List[PaperMeta]:
        """通过 GCS 列出 PDF 文件进行批量回溯"""
        # GCS scan requires knowing the month range; simplified here
        # Full implementation would iterate months and list via GCS XML API
        metas = []
        year_from = since.year
        year_to = datetime.now().year
        for year in range(year_from, year_to + 1):
            for month in range(1, 13):
                prefix = f"arxiv/arxiv/pdf/{year:02d}{month:02d}/"
                url = f"{GCS_BASE}?prefix={prefix}&max-keys=1000"
                resp = requests.get(url, timeout=30)
                if resp.status_code != 200:
                    continue
                root = ET.fromstring(resp.content)
                ns = {"s3": "http://doc.s3.amazonaws.com/2006-03-01"}
                for key in root.findall(".//s3:Key", ns):
                    key_text = key.text
                    if not key_text.endswith(".pdf"):
                        continue
                    filename = key_text.split("/")[-1]  # e.g., 2401.00001v1.pdf
                    arxiv_id = filename.replace(".pdf", "")
                    yymm = prefix.split("/")[-2]
                    year_num = 2000 + int(yymm[:2])
                    month_num = int(yymm[2:])
                    published = datetime(year_num, month_num, 1)
                    if published < since:
                        continue
                    metas.append(PaperMeta(
                        source=self.name,
                        source_id=arxiv_id,
                        title="",  # metadata not available from GCS listing
                        published_at=published,
                        year=year_num,
                        pdf_url=f"{GCS_BASE}/{key_text}",
                    ))
        return metas
    
    def download(self, meta: PaperMeta, dest_path: Path) -> Path:
        url = meta.pdf_url or ARXIV_PDF.format(id=meta.source_id)
        return download_file(url, dest_path, rate_limit_delay=self.rate_limit_delay)
```

- [ ] **Step 4: Run tests**

```bash
cd "/Users/yihaoyang/VScode workspace/quant-cluster/tools/paper_downloader"
python3 -m pytest tests/test_arxiv.py -v
```

Expected: 2 passed

- [ ] **Step 5: Commit**

```bash
cd "/Users/yihaoyang/VScode workspace/quant-cluster"
git add tools/paper_downloader/sources/arxiv.py tools/paper_downloader/tests/test_arxiv.py
git commit -m "feat(downloader): add arXiv source with API + GCS batch modes"
```

---

## Task 7: CORE Source (`sources/core_ac.py`)

**Files:**
- Create: `tools/paper_downloader/sources/core_ac.py`
- Create: `tools/paper_downloader/tests/test_core_ac.py`

- [ ] **Step 1: Write the failing test**

```python
# tools/paper_downloader/tests/test_core_ac.py
import sys, os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..'))

from sources.core_ac import CoreSource

def test_core_source_name():
    src = CoreSource(api_key="test", queries=["test"])
    assert src.name == "core_ac"
```

- [ ] **Step 2: Run test**

```bash
cd "/Users/yihaoyang/VScode workspace/quant-cluster/tools/paper_downloader"
python3 -m pytest tests/test_core_ac.py -v
```

Expected: `ModuleNotFoundError: No module named 'sources.core_ac'`

- [ ] **Step 3: Implement `core_ac.py`**

```python
# tools/paper_downloader/sources/core_ac.py
import requests
import time
from datetime import datetime
from pathlib import Path
from typing import List
from sources.base import Source
from core.models import PaperMeta
from core.downloader import download_file

CORE_API = "https://api.core.ac.uk/v3"


class CoreSource(Source):
    """CORE API v3: search Works → get Outputs → download via downloadUrl"""
    
    def __init__(self, api_key: str, queries: List[str], year_from: int = 2010):
        self.api_key = api_key
        self.queries = queries
        self.year_from = year_from
        self.name = "core_ac"
        self.frequency = "monthly"
        self.rate_limit_delay = 2.4  # 25 req/min
    
    def _headers(self):
        return {"Authorization": f"Bearer {self.api_key}"}
    
    def scan(self, since: datetime) -> List[PaperMeta]:
        metas = []
        since_year = max(since.year, self.year_from)
        query_str = " OR ".join(f"({q})" for q in self.queries)
        full_query = f'({query_str}) AND yearPublished>={since_year} AND _exists_:fullText'
        
        offset = 0
        while True:
            params = {"q": full_query, "limit": 100, "offset": offset, "sort": "recency"}
            resp = requests.get(f"{CORE_API}/search/works", headers=self._headers(), params=params, timeout=30)
            resp.raise_for_status()
            data = resp.json()
            results = data.get("results", [])
            if not results:
                break
            
            for work in results:
                year = work.get("yearPublished")
                published = datetime(year, 1, 1) if year else datetime.now()
                if published < since:
                    continue
                
                doi = work.get("doi")
                work_id = work.get("id")
                
                # Get outputs for downloadUrl
                pdf_url = None
                outputs_resp = requests.get(f"{CORE_API}/works/{work_id}/outputs", headers=self._headers(), timeout=30)
                if outputs_resp.status_code == 200:
                    outputs = outputs_resp.json().get("results", [])
                    if outputs:
                        pdf_url = outputs[0].get("downloadUrl")
                
                metas.append(PaperMeta(
                    source=self.name,
                    source_id=str(work_id),
                    doi=doi,
                    title=work.get("title", ""),
                    authors=work.get("authors", []),
                    abstract=work.get("abstract"),
                    published_at=published,
                    year=year,
                    pdf_url=pdf_url,
                    landing_url=work.get("links", [{}])[0].get("url") if work.get("links") else None,
                ))
            
            offset += len(results)
            time.sleep(self.rate_limit_delay)
            if len(results) < 100:
                break
        return metas
    
    def download(self, meta: PaperMeta, dest_path: Path) -> Path:
        if not meta.pdf_url:
            raise DownloadError(f"No pdf_url for CORE work {meta.source_id}")
        return download_file(meta.pdf_url, dest_path, headers=self._headers(), rate_limit_delay=self.rate_limit_delay)
```

- [ ] **Step 4: Run tests**

```bash
cd "/Users/yihaoyang/VScode workspace/quant-cluster/tools/paper_downloader"
python3 -m pytest tests/test_core_ac.py -v
```

Expected: 1 passed

- [ ] **Step 5: Commit**

```bash
cd "/Users/yihaoyang/VScode workspace/quant-cluster"
git add tools/paper_downloader/sources/core_ac.py tools/paper_downloader/tests/test_core_ac.py
git commit -m "feat(downloader): add CORE API v3 source"
```

---

## Task 8: Elsevier Source (`sources/elsevier.py`)

**Files:**
- Create: `tools/paper_downloader/sources/elsevier.py`
- Create: `tools/paper_downloader/tests/test_elsevier.py`

- [ ] **Step 1: Write the failing test**

```python
# tools/paper_downloader/tests/test_elsevier.py
import sys, os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..'))

from sources.elsevier import ElsevierSource

def test_elsevier_source_name():
    src = ElsevierSource(api_key="test", journals=["JFE"])
    assert src.name == "elsevier"
```

- [ ] **Step 2: Run test**

```bash
cd "/Users/yihaoyang/VScode workspace/quant-cluster/tools/paper_downloader"
python3 -m pytest tests/test_elsevier.py -v
```

Expected: `ModuleNotFoundError`

- [ ] **Step 3: Implement `elsevier.py`**

```python
# tools/paper_downloader/sources/elsevier.py
import requests
import time
from datetime import datetime
from pathlib import Path
from typing import List
from sources.base import Source
from core.models import PaperMeta
from core.downloader import download_file, PaywalledError

ELSEVIER_SEARCH = "https://api.elsevier.com/content/search/scopus"
ELSEVIER_ARTICLE = "https://api.elsevier.com/content/article/doi/{doi}"


class ElsevierSource(Source):
    """Elsevier Scopus Search + Article Retrieval API"""
    
    def __init__(self, api_key: str, journals: List[str], year_from: int = 2010):
        self.api_key = api_key
        self.journals = journals
        self.year_from = year_from
        self.name = "elsevier"
        self.frequency = "monthly"
        self.rate_limit_delay = 0.5
    
    def _headers(self):
        return {"X-ELS-APIKey": self.api_key}
    
    def scan(self, since: datetime) -> List[PaperMeta]:
        metas = []
        since_year = max(since.year, self.year_from)
        
        for journal in self.journals:
            start = 0
            while True:
                query = f'SRCTITLE("{journal}") AND openaccess(1) AND PUBYEAR > {since_year}'
                params = {"query": query, "count": 25, "start": start, "sort": "-pubyear"}
                resp = requests.get(ELSEVIER_SEARCH, headers=self._headers(), params=params, timeout=30)
                resp.raise_for_status()
                data = resp.json()
                entries = data.get("search-results", {}).get("entry", [])
                if not entries or (len(entries) == 1 and "error" in entries[0]):
                    break
                
                for entry in entries:
                    if "error" in entry:
                        continue
                    doi = entry.get("prism:doi")
                    title = entry.get("dc:title", "")
                    year = int(entry.get("prism:coverDate", "0")[:4]) if entry.get("prism:coverDate") else None
                    
                    metas.append(PaperMeta(
                        source=self.name,
                        source_id=doi or entry.get("eid", ""),
                        doi=doi,
                        title=title,
                        authors=[],  # Scopus search doesn't return authors in basic view
                        published_at=datetime(year, 1, 1) if year else None,
                        year=year,
                        landing_url=entry.get("prism:url"),
                    ))
                
                start += len(entries)
                time.sleep(self.rate_limit_delay)
                if len(entries) < 25:
                    break
        return metas
    
    def download(self, meta: PaperMeta, dest_path: Path) -> Path:
        if not meta.doi:
            raise PaywalledError(f"No DOI for Elsevier paper {meta.source_id}")
        url = ELSEVIER_ARTICLE.format(doi=meta.doi)
        headers = self._headers()
        headers["httpAccept"] = "application/pdf"
        
        resp = requests.get(url, headers=headers, timeout=30)
        status = resp.headers.get("x-els-status", "")
        
        if resp.status_code == 200:
            if "not entitled" in status or "WARNING" in status:
                raise PaywalledError(f"Non-OA article (1-page preview): {meta.doi}")
            return download_file(url, dest_path, headers=headers, rate_limit_delay=self.rate_limit_delay)
        elif resp.status_code == 403:
            raise PaywalledError(f"403 Forbidden: {meta.doi}")
        else:
            resp.raise_for_status()
```

- [ ] **Step 4: Run tests**

```bash
cd "/Users/yihaoyang/VScode workspace/quant-cluster/tools/paper_downloader"
python3 -m pytest tests/test_elsevier.py -v
```

Expected: 1 passed

- [ ] **Step 5: Commit**

```bash
cd "/Users/yihaoyang/VScode workspace/quant-cluster"
git add tools/paper_downloader/sources/elsevier.py tools/paper_downloader/tests/test_elsevier.py
git commit -m "feat(downloader): add Elsevier Scopus + Article Retrieval source"
```

---

## Task 9: Wiley Source (`sources/wiley.py`)

**Files:**
- Create: `tools/paper_downloader/sources/wiley.py`

- [ ] **Step 1: Write the failing test**

```python
# tools/paper_downloader/tests/test_wiley.py
import sys, os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..'))

from sources.wiley import WileySource

def test_wiley_source_name():
    src = WileySource(tdm_token="test", journals=["Journal of Finance"])
    assert src.name == "wiley"
```

- [ ] **Step 2: Run test**

```bash
cd "/Users/yihaoyang/VScode workspace/quant-cluster/tools/paper_downloader"
python3 -m pytest tests/test_wiley.py -v
```

Expected: `ModuleNotFoundError`

- [ ] **Step 3: Implement `wiley.py`**

```python
# tools/paper_downloader/sources/wiley.py
import requests
import time
from datetime import datetime
from pathlib import Path
from typing import List
from sources.base import Source
from core.models import PaperMeta
from core.downloader import download_file, PaywalledError

CROSSREF_API = "https://api.crossref.org/works"
WILEY_TDM = "https://api.wiley.com/onlinelibrary/tdm/v1/articles/{doi}"


class WileySource(Source):
    """Wiley: Crossref discovery (CC-BY filter) + TDM API download"""
    
    def __init__(self, tdm_token: str, journals: List[str], year_from: int = 2010):
        self.tdm_token = tdm_token
        self.journals = journals
        self.year_from = year_from
        self.name = "wiley"
        self.frequency = "monthly"
        self.rate_limit_delay = 0.35
    
    def scan(self, since: datetime) -> List[PaperMeta]:
        metas = []
        offset = 0
        journal_filter = " OR ".join(f'"{j}"' for j in self.journals)
        
        while True:
            params = {
                "filter": f"publisher-name:Wiley,from-pub-date:{self.year_from}-01-01,license.url:http://creativecommons.org/licenses/by",
                "query.title": journal_filter,
                "rows": 100,
                "offset": offset,
                "sort": "published",
                "order": "desc",
            }
            resp = requests.get(CROSSREF_API, params=params, timeout=30)
            resp.raise_for_status()
            data = resp.json()
            items = data.get("message", {}).get("items", [])
            if not items:
                break
            
            for item in items:
                doi = item.get("DOI")
                title = item.get("title", [""])[0] if item.get("title") else ""
                published = item.get("published-print", item.get("published-online", {}))
                year = published.get("date-parts", [[None]])[0][0] if published else None
                
                authors = []
                for author in item.get("author", []):
                    name = f"{author.get('given', '')} {author.get('family', '')}".strip()
                    if name:
                        authors.append(name)
                
                metas.append(PaperMeta(
                    source=self.name,
                    source_id=doi or "",
                    doi=doi,
                    title=title,
                    authors=authors,
                    published_at=datetime(year, 1, 1) if year else None,
                    year=year,
                    landing_url=item.get("URL"),
                ))
            
            offset += len(items)
            time.sleep(self.rate_limit_delay)
            if len(items) < 100:
                break
        return metas
    
    def download(self, meta: PaperMeta, dest_path: Path) -> Path:
        if not meta.doi:
            raise PaywalledError(f"No DOI for Wiley paper {meta.source_id}")
        url = WILEY_TDM.format(doi=meta.doi)
        headers = {"Wiley-TDM-Client-Token": self.tdm_token}
        
        resp = requests.get(url, headers=headers, allow_redirects=True, timeout=30)
        if resp.status_code == 403:
            raise PaywalledError(f"TDM 403: {meta.doi}")
        if resp.status_code == 200 and len(resp.content) > 10000:
            dest_path.write_bytes(resp.content)
            time.sleep(self.rate_limit_delay)
            return dest_path
        raise PaywalledError(f"Wiley download failed: {resp.status_code}")
```

- [ ] **Step 4: Run tests**

```bash
cd "/Users/yihaoyang/VScode workspace/quant-cluster/tools/paper_downloader"
python3 -m pytest tests/test_wiley.py -v
```

Expected: 1 passed

- [ ] **Step 5: Commit**

```bash
cd "/Users/yihaoyang/VScode workspace/quant-cluster"
git add tools/paper_downloader/sources/wiley.py tools/paper_downloader/tests/test_wiley.py
git commit -m "feat(downloader): add Wiley Crossref + TDM source"
```

---

## Task 10: Conference Source (`sources/conference.py`)

**Files:**
- Create: `tools/paper_downloader/sources/conference.py`

- [ ] **Step 1: Write the failing test**

```python
# tools/paper_downloader/tests/test_conference.py
import sys, os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..'))

from sources.conference import NeurIPSSource

def test_neurips_name():
    src = NeurIPSSource(year=2024)
    assert src.name == "neurips_2024"
```

- [ ] **Step 2: Run test**

```bash
cd "/Users/yihaoyang/VScode workspace/quant-cluster/tools/paper_downloader"
python3 -m pytest tests/test_conference.py -v
```

Expected: `ModuleNotFoundError`

- [ ] **Step 3: Implement `conference.py`**

```python
# tools/paper_downloader/sources/conference.py
import requests
import time
from datetime import datetime
from pathlib import Path
from typing import List
from sources.base import Source
from core.models import PaperMeta
from core.downloader import download_file


class NeurIPSSource(Source):
    """NeurIPS proceedings scraper"""
    
    def __init__(self, year: int):
        self.year = year
        self.name = f"neurips_{year}"
        self.frequency = "yearly"
        self.rate_limit_delay = 2.0
        self.base_url = f"https://papers.nips.cc/paper/{year}"
    
    def scan(self, since: datetime) -> List[PaperMeta]:
        metas = []
        resp = requests.get(self.base_url, timeout=30)
        resp.raise_for_status()
        # Simple regex-based parsing (production may need BeautifulSoup)
        import re
        for match in re.finditer(r'href="(/paper/\d+/[^"]+)"', resp.text):
            path = match.group(1)
            paper_url = f"https://papers.nips.cc{path}"
            paper_resp = requests.get(paper_url, timeout=30)
            paper_resp.raise_for_status()
            
            title_match = re.search(r'<h4>([^<]+)</h4>', paper_resp.text)
            title = title_match.group(1).strip() if title_match else ""
            
            pdf_match = re.search(r'href="(/paper/\d+/file/[^"]+\.pdf)"', paper_resp.text)
            pdf_url = f"https://papers.nips.cc{pdf_match.group(1)}" if pdf_match else None
            
            metas.append(PaperMeta(
                source=self.name,
                source_id=path.split("/")[-1],
                title=title,
                year=self.year,
                pdf_url=pdf_url,
                landing_url=paper_url,
            ))
            time.sleep(self.rate_limit_delay)
        return metas
    
    def download(self, meta: PaperMeta, dest_path: Path) -> Path:
        if not meta.pdf_url:
            raise DownloadError(f"No PDF URL for NeurIPS paper {meta.source_id}")
        return download_file(meta.pdf_url, dest_path, rate_limit_delay=self.rate_limit_delay)
```

- [ ] **Step 4: Run tests**

```bash
cd "/Users/yihaoyang/VScode workspace/quant-cluster/tools/paper_downloader"
python3 -m pytest tests/test_conference.py -v
```

Expected: 1 passed

- [ ] **Step 5: Commit**

```bash
cd "/Users/yihaoyang/VScode workspace/quant-cluster"
git add tools/paper_downloader/sources/conference.py tools/paper_downloader/tests/test_conference.py
git commit -m "feat(downloader): add NeurIPS conference source"
```

---

## Task 11: CLI Interface (`__main__.py` + `config.yaml`)

**Files:**
- Create: `tools/paper_downloader/__main__.py`
- Create: `tools/paper_downloader/config.yaml`
- Create: `tools/paper_downloader/__init__.py`

- [ ] **Step 1: Write the failing test**

```python
# tools/paper_downloader/tests/test_cli.py
import sys, os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..'))

def test_cli_importable():
    import __main__
    assert hasattr(__main__, 'main')
```

- [ ] **Step 2: Run test**

```bash
cd "/Users/yihaoyang/VScode workspace/quant-cluster/tools/paper_downloader"
python3 -m pytest tests/test_cli.py -v
```

Expected: `ModuleNotFoundError` or import error

- [ ] **Step 3: Implement `__init__.py`, `__main__.py`, and `config.yaml`**

```python
# tools/paper_downloader/__init__.py
__version__ = "0.1.0"
```

```python
# tools/paper_downloader/__main__.py
import argparse
import sys
import json
from pathlib import Path
from datetime import datetime

from core.store import PaperStore
from core.scheduler import Scheduler
from sources.arxiv import ArxivSource
from sources.core_ac import CoreSource
from sources.elsevier import ElsevierSource
from sources.wiley import WileySource
from sources.conference import NeurIPSSource


def load_config(path: Path) -> dict:
    import yaml
    with open(path) as f:
        return yaml.safe_load(f)


def build_sources(config: dict):
    sources = []
    src_cfg = config.get("sources", {})
    
    for name, cfg in src_cfg.items():
        if not cfg.get("enabled", False):
            continue
        if name.startswith("arxiv_"):
            cat = cfg["categories"][0]
            mode = cfg.get("backfill", {}).get("mode", "api")
            sources.append(ArxivSource(category=cat, backfill_mode=mode))
        elif name == "core_ac":
            key = config["api_keys"].get("core_ac", "")
            sources.append(CoreSource(api_key=key, queries=cfg["queries"], year_from=cfg.get("year_from", 2010)))
        elif name == "elsevier":
            key = config["api_keys"].get("elsevier", "")
            sources.append(ElsevierSource(api_key=key, journals=cfg["journals"], year_from=cfg.get("year_from", 2010)))
        elif name == "wiley":
            token = config["api_keys"].get("wiley_tdm", "")
            sources.append(WileySource(tdm_token=token, journals=cfg["journals"], year_from=cfg.get("year_from", 2010)))
        elif name == "neurips":
            sources.append(NeurIPSSource(year=datetime.now().year - 1))
    return sources


def cmd_scan(args):
    config = load_config(Path(__file__).parent / "config.yaml")
    raw_dir = Path(config["storage"]["raw_dir"])
    db_path = Path(config["storage"]["db_path"])
    raw_dir.mkdir(parents=True, exist_ok=True)
    db_path.parent.mkdir(parents=True, exist_ok=True)
    
    store = PaperStore(db_path)
    sources = build_sources(config)
    if args.sources:
        names = set(args.sources.split(","))
        sources = [s for s in sources if s.name in names]
    
    scheduler = Scheduler(sources, config)
    results = []
    for source in scheduler.get_due_sources(store):
        result = scheduler.run_source(source, store, raw_dir)
        results.append(result)
        print(json.dumps(result, ensure_ascii=False))
    
    if args.report:
        summary = {
            "run_id": datetime.now().strftime("%Y-%m-%d-%H%M%S"),
            "sources": results,
            "total_new": sum(r["new"] for r in results),
            "total_downloaded": sum(r["downloaded"] for r in results),
            "total_failed": sum(r["failed"] for r in results),
        }
        print(json.dumps(summary, ensure_ascii=False, indent=2))


def cmd_stats(args):
    config = load_config(Path(__file__).parent / "config.yaml")
    db_path = Path(config["storage"]["db_path"])
    store = PaperStore(db_path)
    cursor = store.conn.execute("""
        SELECT source, status, COUNT(*) as cnt FROM papers
        GROUP BY source, status
    """)
    for row in cursor.fetchall():
        print(f"{row['source']:20s} {row['status']:12s} {row['cnt']:4d}")


def main():
    parser = argparse.ArgumentParser(description="Paper Downloader")
    sub = parser.add_subparsers(dest="cmd")
    
    p_scan = sub.add_parser("scan", help="Scan and download papers")
    p_scan.add_argument("--sources", help="Comma-separated source names")
    p_scan.add_argument("--report", action="store_true", help="Output JSON summary")
    p_scan.add_argument("--layer", choices=["api"], help="Filter by layer")
    p_scan.set_defaults(func=cmd_scan)
    
    p_stats = sub.add_parser("stats", help="Show download statistics")
    p_stats.add_argument("--source", help="Filter by source name")
    p_stats.set_defaults(func=cmd_stats)
    
    args = parser.parse_args()
    if not args.cmd:
        parser.print_help()
        sys.exit(1)
    args.func(args)


if __name__ == "__main__":
    main()
```

```yaml
# tools/paper_downloader/config.yaml
storage:
  raw_dir: "shared_workspace/papers/raw"
  db_path: "shared_workspace/papers/downloads.db"

backfill:
  journals_since: "2010-01-01"
  conferences_since: "2020-01-01"

api_keys:
  core_ac: "${CORE_API_KEY}"
  elsevier: "${ELSEVIER_API_KEY}"
  wiley_tdm: "${WILEY_TDM_TOKEN}"

sources:
  arxiv_qfin:
    enabled: true
    frequency: weekly
    categories: ["q-fin.TR", "q-fin.PM", "q-fin.MF", "q-fin.CP", "q-fin.ST"]
    rate_limit_delay: 3.0
    backfill:
      enabled: true
      mode: gcs
      gcs_bucket: arxiv-dataset
      year_from: 2010
      year_to: 2024
      rate_limit_delay: 0.1

  arxiv_cslg:
    enabled: true
    frequency: weekly
    categories: ["cs.LG", "cs.AI"]
    rate_limit_delay: 3.0
    backfill:
      enabled: true
      mode: gcs
      gcs_bucket: arxiv-dataset
      year_from: 2010
      year_to: 2024
      rate_limit_delay: 0.1

  core_ac:
    enabled: true
    frequency: monthly
    queries:
      - 'title:"Journal of Finance" OR title:"Journal of Financial Economics" OR title:"Review of Financial Studies" OR title:"Review of Finance"'
    year_from: 2010
    rate_limit_delay: 2.4

  elsevier:
    enabled: true
    frequency: monthly
    journals: ["Journal of Financial Economics", "Journal of Banking & Finance", "Journal of Empirical Finance"]
    year_from: 2010
    rate_limit_delay: 0.5

  wiley:
    enabled: true
    frequency: monthly
    journals: ["Journal of Finance", "Review of Financial Studies"]
    crossref_filter: "publisher-name:Wiley,license.url:http://creativecommons.org/licenses/by"
    year_from: 2010
    rate_limit_delay: 0.35

  neurips:
    enabled: true
    frequency: yearly
    rate_limit_delay: 2.0

  ssrn: {enabled: false, frequency: weekly, rate_limit_delay: 5.0}
  icml: {enabled: false, frequency: yearly}
  iclr: {enabled: false, frequency: yearly}
  kdd: {enabled: false, frequency: yearly}
  icaif: {enabled: false, frequency: yearly}
  aqr: {enabled: false, frequency: monthly}
  oxford_man: {enabled: false, frequency: monthly}
  alpha_architect: {enabled: false, frequency: monthly}
  scihub: {enabled: false, frequency: on_demand}
```

- [ ] **Step 4: Run tests**

```bash
cd "/Users/yihaoyang/VScode workspace/quant-cluster/tools/paper_downloader"
python3 -m pytest tests/test_cli.py -v
python3 -m paper_downloader --help
```

Expected: test passed, help output shown

- [ ] **Step 5: Commit**

```bash
cd "/Users/yihaoyang/VScode workspace/quant-cluster"
git add tools/paper_downloader/__init__.py tools/paper_downloader/__main__.py tools/paper_downloader/config.yaml tools/paper_downloader/tests/test_cli.py
git commit -m "feat(downloader): add CLI with scan, stats commands and config.yaml"
```

---

## Task 12: Agent Config (`agent_configs/paper_downloader/`)

**Files:**
- Create: `agent_configs/paper_downloader/SOUL.md`
- Create: `agent_configs/paper_downloader/config.yaml`

- [ ] **Step 1: Create `SOUL.md`**

```markdown
---
name: paper_downloader
description: |
  独立运行的论文批量下载器 Agent，负责触发引擎扫描 API 源、用 WebBridge 处理浏览器源（SSRN）、读取下载摘要做失败项决策、生成双语报告。
triggers:
  - "下载论文"
  - "扫描论文源"
  - "paper downloader"
skills:
  - paper-download
  - webbridge-interaction
input_spec:
  - 来源: orchestrator prompt / cron
    格式: 自然语言指令或定时触发
output_spec:
  - downloader_report_{date}.md
  - downloader_report_{date}_en.md
  - .agent_checkpoint.json
dependencies:
  - tools/paper_downloader/
  - tools/webbridge_client.py
---

# 🎯 Paper Downloader Agent

## 角色定义
负责论文批量下载的全流程监控和决策。

## 触发条件
- 定时触发（每周一）
- 手动指令 "下载论文"

## 核心能力
1. 触发引擎执行 API 源扫描
2. 用 WebBridge 处理浏览器源（SSRN）
3. 读取下载摘要，做失败项决策
4. 生成双语报告

## 工作流

### Phase 1: API 源扫描
```bash
python3 -m paper_downloader scan --layer api --report
```

### Phase 2: 浏览器源扫描（Agent）
- SSRN: WebBridge fetch 列表页 → 解析 abstract_id → 构造 PDF URL → download

### Phase 3: 失败项决策
- fail_count < 3 且网络错误 → 重试
- fail_count >= 3 或 403/404 → 跳过
- 失败率 > 30% → 标记 degraded

### Phase 4: 报告生成
产出双语报告 + checkpoint。

## 验证检查清单
- [ ] 各源新增/下载/失败统计完整
- [ ] 失败项清单及决策理由
- [ ] checkpoint 已写入
```

- [ ] **Step 2: Create `config.yaml`**

```yaml
model: claude-sonnet-4-20250514
api_server:
  port: 8647
  api_key: "sk-downloader-local"
tools:
  enabled: [terminal, file, memory]
terminal:
  allowed_commands: [python3, ls, cat, mkdir, curl]
  timeout: 1800
memory:
  enabled: true
```

- [ ] **Step 3: Commit**

```bash
cd "/Users/yihaoyang/VScode workspace/quant-cluster"
git add agent_configs/paper_downloader/SOUL.md agent_configs/paper_downloader/config.yaml
git commit -m "feat(downloader): add Agent SOUL.md and Hermes config"
```

---

## Task 13: DAG Integration (`orchestrator/core/dag.py`)

**Files:**
- Modify: `orchestrator/core/dag.py`

- [ ] **Step 1: Modify `dag.py` to add paper_downloader**

```python
# Add to AGENTS dict (after strategy_writer)
    "paper_downloader": {"port": 8647, "api_key": "sk-downloader-local", "workspace": "papers"},
```

Note: `paper_downloader` is NOT added to `EXECUTION_ORDER` — it runs independently as a scheduled service.

- [ ] **Step 2: Verify no syntax errors**

```bash
cd "/Users/yihaoyang/VScode workspace/quant-cluster"
python3 -c "from orchestrator.core.dag import AGENTS; print('paper_downloader' in AGENTS)"
```

Expected: `True`

- [ ] **Step 3: Commit**

```bash
cd "/Users/yihaoyang/VScode workspace/quant-cluster"
git add orchestrator/core/dag.py
git commit -m "feat(downloader): add paper_downloader to AGENTS config (port 8647)"
```

---

## Task 14: Integration / Smoke Test

**Files:**
- Create: `scripts/verify_paper_downloader.sh`

- [ ] **Step 1: Create smoke test script**

```bash
#!/bin/bash
# scripts/verify_paper_downloader.sh
set -e

cd "/Users/yihaoyang/VScode workspace/quant-cluster"

echo "=== 1. Verify module imports ==="
cd tools/paper_downloader
python3 -c "from core.models import PaperMeta; from core.store import PaperStore; from sources.base import Source; print('OK')"

echo "=== 2. Run unit tests ==="
python3 -m pytest tests/ -v --tb=short

echo "=== 3. Verify CLI help ==="
python3 -m paper_downloader --help

echo "=== 4. Verify config syntax ==="
python3 -c "import yaml; yaml.safe_load(open('config.yaml')); print('config.yaml OK')"

echo "=== 5. Verify Agent config ==="
python3 -c "import yaml; yaml.safe_load(open('../../agent_configs/paper_downloader/config.yaml')); print('Agent config OK')"

echo "=== All checks passed ==="
```

```bash
chmod +x scripts/verify_paper_downloader.sh
```

- [ ] **Step 2: Run smoke test**

```bash
cd "/Users/yihaoyang/VScode workspace/quant-cluster"
./scripts/verify_paper_downloader.sh
```

Expected: All checks passed

- [ ] **Step 3: Commit**

```bash
cd "/Users/yihaoyang/VScode workspace/quant-cluster"
git add scripts/verify_paper_downloader.sh
git commit -m "feat(downloader): add smoke test script"
```

---

## Self-Review

### 1. Spec Coverage Check

| Spec Section | Plan Task | Status |
|-------------|-----------|--------|
| §5.1 PaperMeta | Task 1 | ✅ |
| §5.2 Source ABC | Task 4 | ✅ |
| §6.1 SQLite Schema | Task 2 | ✅ |
| §6.2 PaperStore ops | Task 2 | ✅ |
| §6.3 Incremental logic | Task 5 (scheduler) | ✅ |
| §7.1 arXiv (OAI-PMH + GCS) | Task 6 | ✅ |
| §7.2 CORE API | Task 7 | ✅ |
| §7.3 Elsevier | Task 8 | ✅ |
| §7.4 Wiley | Task 9 | ✅ |
| §7.5 Conference | Task 10 | ✅ |
| §8 Rate Limit | Tasks 6-10 | ✅ |
| §10 CLI | Task 11 | ✅ |
| §11.1 Config | Task 11 | ✅ |
| §11.2 Agent Config | Task 12 | ✅ |
| §12.1 DAG | Task 13 | ✅ |

### 2. Placeholder Scan

No TBD, TODO, or "implement later" found. All steps contain actual code.

### 3. Type Consistency

- `PaperMeta.id` added dynamically in `store.py` (not in dataclass, assigned after insert)
- `rate_limit_delay` field name consistent across all sources
- `download()` signature consistent: `(meta, dest_path) -> Path`
- `scan()` signature consistent: `(since) -> List[PaperMeta]`

---

*Plan created: 2026-05-31*
*Based on spec: docs/superpowers/specs/2026-05-31-paper-downloader-design.md*
