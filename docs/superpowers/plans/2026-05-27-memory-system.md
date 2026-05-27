# Memory System Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build a file-based persistent memory system (`memory/`) that stores condensed insights across pipeline runs, with automatic recall injection into Agent prompts.

**Architecture:** Pure Python file-based storage (Markdown + YAML frontmatter) with character-level token matching for CJK/ASCII search. No external DB. Kimi Code performs extraction via Skill; Orchestrator injects relevant memories into Agent system prompts at runtime.

**Tech Stack:** Python 3.11+ stdlib only. No pip dependencies.

---

## File Structure

```
memory/                          # NEW — storage/retrieval/CLI module
├── __init__.py                  # exports PersistentMemory, MemoryEntry
├── persistent.py                # core: add/remove/find/search/index
└── __main__.py                  # CLI: add/search/list/show

tests/memory/                    # NEW — test suite
├── __init__.py
└── test_persistent.py           # unit tests for PersistentMemory

orchestrator/core/orchestrator.py  # MODIFY — _execute_agent() recall injection

agent_configs/                   # MODIFY — 5 SOUL.md files
├── hypothesis/SOUL.md
├── data_engineer/SOUL.md
├── quant_analyst/SOUL.md
├── risk_auditor/SOUL.md
└── strategy_writer/SOUL.md

.kimi/skills/quant-cluster/SKILL.md  # MODIFY — add Memory extraction section
```

---

## Task 1: `memory/persistent.py` — Core Storage and Retrieval

**Files:**
- Create: `memory/__init__.py`
- Create: `memory/persistent.py`
- Test: `tests/memory/__init__.py`

**Context:** This module is a standalone port of Vibe-Trading's `agent/src/memory/persistent.py`, adapted for Quant Cluster. It uses file-based storage with YAML frontmatter markdown files. Search is pure Python set intersection — no SQLite, no jieba, no vector DB.

---

- [ ] **Step 1: Create `memory/__init__.py`**

```python
"""Quant Cluster memory module — persistent cross-run research memory."""

from memory.persistent import MemoryEntry, PersistentMemory

__all__ = ["MemoryEntry", "PersistentMemory"]
```

- [ ] **Step 2: Create `tests/memory/__init__.py`**

```python
"""Tests for memory module."""
```

- [ ] **Step 3: Write `memory/persistent.py` — frontmatter parser**

Write the file in parts. First, the YAML-like frontmatter parser (simplified from Vibe-Trading's `parse_frontmatter`):

```python
"""PersistentMemory: file-based cross-session memory, zero external dependencies."""

from __future__ import annotations

import hashlib
import logging
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Dict, List, Optional

logger = logging.getLogger(__name__)

MEMORY_BASE = Path.home() / ".quant-cluster" / "memory"
MAX_INDEX_LINES = 200
MAX_ENTRY_CHARS = 8000
MAX_RESULTS = 5
METADATA_WEIGHT = 2.0
MEMORY_TYPES = ("user", "feedback", "project", "reference")

# Tokenization: ASCII words >= 3 chars + individual non-Latin chars
_NON_LATIN_SCRIPT_RANGES = (
    "一-鿿"   # CJK Unified Ideographs (U+4E00-U+9FFF)
    "㐀-䶿"   # CJK Extension A (U+3400-U+4DBF)
    "぀-ゟ"   # Hiragana (U+3040-U+309F)
    "゠-ヿ"   # Katakana (U+30A0-U+30FF)
    "㄀-ㄯ"   # Bopomofo (U+3100-U+312F)
    "가-힣"   # Hangul Syllables (U+AC00-U+D7AF)
    "Ѐ-ӿ"   # Cyrillic (U+0400-U+04FF)
)

_TOKEN_RE = re.compile(rf"[a-zA-Z0-9]{{3,}}|[{_NON_LATIN_SCRIPT_RANGES}]")
_SLUG_DISALLOWED_RE = re.compile(rf"[^a-z0-9_\-{_NON_LATIN_SCRIPT_RANGES}]")

# Control char sanitization (C0 + C1, except \t \n)
_CONTROL_CHAR_RE = re.compile(r"[\x00-\x08\x0b\x0c\x0e-\x1f\x7f-\x9f]")

_TRUNCATION_MARKER = "\n\n[truncated at {limit} chars]\n"


def _tokenize(text: str) -> set[str]:
    """Split text into searchable tokens.

    ASCII words >= 3 chars + individual characters from non-Latin scripts.
    Underscores treated as word boundaries so snake_case matches natural queries.
    """
    return set(_TOKEN_RE.findall(text.lower()))


def _sanitize_body(content: str) -> str:
    """Strip C0/C1 control bytes while keeping \\n and \\t."""
    return _CONTROL_CHAR_RE.sub("", content)


def _truncate_body(content: str, limit: int | None = None) -> str:
    """Clip content to limit chars, leaving room for truncation marker."""
    if limit is None:
        limit = MAX_ENTRY_CHARS
    if len(content) <= limit:
        return content
    marker = _TRUNCATION_MARKER.format(limit=limit)
    head_len = max(0, limit - len(marker))
    return content[:head_len] + marker


def _coerce_str(value: object, default: str = "") -> str:
    """Coerce frontmatter values to display string."""
    if value is None:
        return default
    if isinstance(value, str):
        return value
    if isinstance(value, bool):
        return "true" if value else "false"
    if isinstance(value, list):
        return ", ".join(str(v) for v in value)
    return str(value)


def _parse_frontmatter(text: str) -> tuple[Dict[str, Any], str]:
    """Parse YAML-like frontmatter and body from markdown.

    Supports string, list ([a, b]), and boolean values.
    """
    match = re.match(r"^---\s*\n(.*?)\n---\s*\n(.*)", text, re.DOTALL)
    if not match:
        return {}, text.strip()

    meta: Dict[str, Any] = {}
    for line in match.group(1).strip().split("\n"):
        line = line.strip()
        if ":" not in line:
            continue
        key, value = line.split(":", 1)
        key = key.strip()
        value = value.strip()
        if value.startswith("[") and value.endswith("]"):
            items = [item.strip().strip("'\"") for item in value[1:-1].split(",")]
            meta[key] = [i for i in items if i]
        elif value.lower() in ("true", "false"):
            meta[key] = value.lower() == "true"
        else:
            meta[key] = value

    return meta, match.group(2).strip()
```

- [ ] **Step 4: Append `MemoryEntry` dataclass and `PersistentMemory` class to `memory/persistent.py`**

```python

@dataclass(frozen=True)
class MemoryEntry:
    """A single memory entry on disk."""

    path: Path
    title: str
    description: str
    memory_type: str
    body: str
    modified_at: float


class PersistentMemory:
    """File-based persistent memory that survives across sessions.

    Design:
    - Frozen snapshot injected into system prompt at session start.
    - Disk writes via add()/remove() update files immediately but do NOT change snapshot.
    - Next session picks up the updated state.
    """

    def __init__(self, memory_dir: Optional[Path] = None) -> None:
        self._dir = memory_dir or MEMORY_BASE
        self._dir.mkdir(parents=True, exist_ok=True)
        self._index_path = self._dir / "MEMORY.md"
        self._snapshot: str = ""
        self._load_snapshot()

    def _load_snapshot(self) -> None:
        if self._index_path.exists():
            try:
                text = self._index_path.read_text(encoding="utf-8")
                lines = text.split("\n")[:MAX_INDEX_LINES]
                self._snapshot = "\n".join(lines)
            except OSError:
                self._snapshot = ""

    @property
    def snapshot(self) -> str:
        return self._snapshot

    def _scan_entries(self) -> List[MemoryEntry]:
        entries: List[MemoryEntry] = []
        for path in sorted(self._dir.glob("*.md")):
            if path.name == "MEMORY.md":
                continue
            try:
                text = path.read_text(encoding="utf-8")
            except OSError:
                continue
            meta, body = _parse_frontmatter(text)
            entries.append(MemoryEntry(
                path=path,
                title=_coerce_str(meta.get("name"), default=path.stem),
                description=_coerce_str(meta.get("description")),
                memory_type=_coerce_str(meta.get("type"), default="project"),
                body=body[:MAX_ENTRY_CHARS],
                modified_at=path.stat().st_mtime,
            ))
        return entries

    def list_entries(self) -> List[MemoryEntry]:
        return self._scan_entries()

    def find(self, name: str) -> Optional[MemoryEntry]:
        needle = name.strip()
        if not needle:
            return None
        entries = self._scan_entries()
        for entry in entries:
            if entry.title == needle:
                return entry
        for entry in entries:
            stem = entry.path.stem
            if stem == needle or stem.endswith(f"_{needle}"):
                return entry
        return None

    def remove_entry(self, entry: MemoryEntry) -> bool:
        try:
            entry.path.unlink(missing_ok=True)
        except OSError as exc:
            logger.warning("Failed to remove memory entry %s: %s", entry.path, exc)
            return False
        self._rebuild_index()
        return True

    def find_relevant(self, query: str, max_results: int = MAX_RESULTS) -> List[MemoryEntry]:
        query_tokens = _tokenize(query)
        if not query_tokens:
            return []

        scored: list[tuple[float, MemoryEntry]] = []
        for entry in self._scan_entries():
            meta_tokens = _tokenize(f"{entry.title} {entry.description}")
            body_tokens = _tokenize(entry.body)
            score = (
                len(query_tokens & meta_tokens) * METADATA_WEIGHT
                + len(query_tokens & body_tokens)
            )
            if score > 0:
                scored.append((score, entry))

        scored.sort(key=lambda x: (-x[0], -x[1].modified_at))
        return [entry for _, entry in scored[:max_results]]

    def add(
        self,
        name: str,
        content: str,
        memory_type: str = "project",
        description: str = "",
    ) -> Path:
        stripped_name = name.strip()
        if not stripped_name:
            raise ValueError("memory name must not be empty or whitespace-only")

        slug = _SLUG_DISALLOWED_RE.sub("_", stripped_name.lower())[:60]
        if slug.strip("_") == "":
            digest = hashlib.sha256(stripped_name.encode("utf-8")).hexdigest()[:6]
            slug = f"{slug}_{digest}" if slug else digest

        filename = f"{memory_type}_{slug}.md"
        path = self._dir / filename

        safe_name = stripped_name.replace("\n", " ").replace("\r", " ")
        safe_desc = (description or stripped_name).replace("\n", " ").replace("\r", " ")

        clean_content = _truncate_body(_sanitize_body(content))

        frontmatter = (
            f"---\nname: {safe_name}\n"
            f"description: {safe_desc}\n"
            f"type: {memory_type}\n---\n\n"
            f"{clean_content}"
        )
        path.write_text(frontmatter, encoding="utf-8")
        self._update_index(stripped_name, filename, description or stripped_name)
        return path

    def remove(self, name: str) -> bool:
        for entry in self._scan_entries():
            if entry.title == name:
                entry.path.unlink(missing_ok=True)
                self._rebuild_index()
                return True
        return False

    def _update_index(self, title: str, filename: str, description: str) -> None:
        new_line = f"- [{title}]({filename}) — {description}"

        if self._index_path.exists():
            lines = self._index_path.read_text(encoding="utf-8").split("\n")
            updated = False
            for i, line in enumerate(lines):
                if f"[{title}]" in line:
                    lines[i] = new_line
                    updated = True
                    break
            if not updated:
                lines.append(new_line)
            text = "\n".join(lines[:MAX_INDEX_LINES])
        else:
            text = new_line

        self._index_path.write_text(text, encoding="utf-8")

    def _rebuild_index(self) -> None:
        entries = self._scan_entries()
        lines = [f"- [{e.title}]({e.path.name}) — {e.description}" for e in entries]
        self._index_path.write_text("\n".join(lines[:MAX_INDEX_LINES]), encoding="utf-8")
```

- [ ] **Step 5: Verify `memory/persistent.py` is syntactically valid**

Run:
```bash
cd /Users/yihaoyang/VScode\ workspace/quant-cluster
python3 -c "from memory.persistent import PersistentMemory, MemoryEntry; print('import OK')"
```
Expected: `import OK`

- [ ] **Step 6: Commit**

```bash
git add memory/__init__.py memory/persistent.py tests/memory/__init__.py
git commit -m "feat(memory): add PersistentMemory with file-based storage and token search"
```

---

## Task 2: `memory/__main__.py` — CLI Interface

**Files:**
- Create: `memory/__main__.py`

**Context:** Provides a CLI for Kimi Code and users to interact with memory. Four subcommands: `add`, `search`, `list`, `show`.

---

- [ ] **Step 1: Create `memory/__main__.py`**

```python
"""CLI for memory module.

Usage:
    python3 -m memory add --name "..." --content "..." [--type project] [--description "..."]
    python3 -m memory search "query" [--max-results 5]
    python3 -m memory list
    python3 -m memory show "name"
"""

import argparse
import sys
from pathlib import Path

from memory.persistent import PersistentMemory


def cmd_add(args: argparse.Namespace) -> int:
    mem = PersistentMemory()
    content = args.content
    if args.content_file:
        content = Path(args.content_file).read_text(encoding="utf-8")
    path = mem.add(
        name=args.name,
        content=content,
        memory_type=args.type,
        description=args.description or "",
    )
    print(f"Memory saved: {path}")
    return 0


def cmd_search(args: argparse.Namespace) -> int:
    mem = PersistentMemory()
    results = mem.find_relevant(args.query, max_results=args.max_results)
    if not results:
        print("No memories found.")
        return 0
    for i, entry in enumerate(results, 1):
        print(f"{i}. [{entry.memory_type}] {entry.title}")
        if entry.description:
            print(f"   {entry.description}")
        preview = entry.body.replace("\n", " ")[:120]
        print(f"   {preview}...")
    return 0


def cmd_list(_args: argparse.Namespace) -> int:
    mem = PersistentMemory()
    entries = mem.list_entries()
    if not entries:
        print("No memories stored.")
        return 0
    for entry in entries:
        print(f"- [{entry.memory_type}] {entry.title} — {entry.description}")
    return 0


def cmd_show(args: argparse.Namespace) -> int:
    mem = PersistentMemory()
    entry = mem.find(args.name)
    if entry is None:
        print(f"Memory not found: {args.name}")
        return 1
    print(f"# {entry.title}")
    print(f"Type: {entry.memory_type}")
    print(f"Description: {entry.description}")
    print(f"Path: {entry.path}")
    print("---")
    print(entry.body)
    return 0


def main() -> int:
    parser = argparse.ArgumentParser(description="Quant Cluster memory CLI")
    subparsers = parser.add_subparsers(dest="command")

    # add
    add_parser = subparsers.add_parser("add", help="Add or update a memory")
    add_parser.add_argument("--name", required=True)
    add_parser.add_argument("--content", default="")
    add_parser.add_argument("--content-file", default=None, help="Read content from file")
    add_parser.add_argument("--type", default="project", choices=("user", "feedback", "project", "reference"))
    add_parser.add_argument("--description", default="")

    # search
    search_parser = subparsers.add_parser("search", help="Search memories by keyword")
    search_parser.add_argument("query")
    search_parser.add_argument("--max-results", type=int, default=5)

    # list
    subparsers.add_parser("list", help="List all memories")

    # show
    show_parser = subparsers.add_parser("show", help="Show a memory by name")
    show_parser.add_argument("name")

    args = parser.parse_args()
    if args.command == "add":
        return cmd_add(args)
    if args.command == "search":
        return cmd_search(args)
    if args.command == "list":
        return cmd_list(args)
    if args.command == "show":
        return cmd_show(args)

    parser.print_help()
    return 1


if __name__ == "__main__":
    sys.exit(main())
```

- [ ] **Step 2: Verify CLI works**

Run:
```bash
cd /Users/yihaoyang/VScode\ workspace/quant-cluster
python3 -m memory list
```
Expected: `No memories stored.` (or list if ~/.quant-cluster/memory/ has entries)

Run:
```bash
python3 -m memory add --name "测试记忆" --content "## 核心假设\n动量策略有效" --type project --description "一个测试"
```
Expected: `Memory saved: /Users/.../.quant-cluster/memory/project_测试记忆.md`

Run:
```bash
python3 -m memory search "动量"
```
Expected: Shows the test memory.

- [ ] **Step 3: Commit**

```bash
git add memory/__main__.py
git commit -m "feat(memory): add CLI (add/search/list/show)"
```

---

## Task 3: Unit Tests — `tests/memory/test_persistent.py`

**Files:**
- Create: `tests/memory/test_persistent.py`

---

- [ ] **Step 1: Write tests**

```python
"""Unit tests for memory.persistent."""

import json
import tempfile
from pathlib import Path

import pytest

from memory.persistent import PersistentMemory, _tokenize, _parse_frontmatter


class TestTokenize:
    def test_ascii_words(self):
        assert _tokenize("momentum strategy backtest") == {"momentum", "strategy", "backtest"}

    def test_underscore_boundary(self):
        assert _tokenize("momentum_strategy") == {"momentum", "strategy"}

    def test_cjk_chars(self):
        tokens = _tokenize("动量策略")
        assert tokens == {"动", "量", "策", "略"}

    def test_mixed(self):
        tokens = _tokenize("momentum动量")
        assert "momentum" in tokens
        assert "动" in tokens
        assert "量" in tokens

    def test_short_ascii_ignored(self):
        assert _tokenize("a bc") == set()


class TestParseFrontmatter:
    def test_basic(self):
        text = "---\nname: Test\ntype: project\n---\n\nBody here."
        meta, body = _parse_frontmatter(text)
        assert meta == {"name": "Test", "type": "project"}
        assert body == "Body here."

    def test_no_frontmatter(self):
        text = "Just body."
        meta, body = _parse_frontmatter(text)
        assert meta == {}
        assert body == "Just body."

    def test_list_value(self):
        text = "---\ntags: [a, b, c]\n---\n\nBody"
        meta, body = _parse_frontmatter(text)
        assert meta["tags"] == ["a", "b", "c"]

    def test_bool_value(self):
        text = "---\nactive: true\n---\n\nBody"
        meta, body = _parse_frontmatter(text)
        assert meta["active"] is True


class TestPersistentMemory:
    @pytest.fixture
    def mem(self, tmp_path):
        return PersistentMemory(memory_dir=tmp_path)

    def test_add_and_find(self, mem):
        path = mem.add("动量策略", "## 假设\n动量有效", type="project", description="测试")
        assert path.exists()

        entry = mem.find("动量策略")
        assert entry is not None
        assert entry.title == "动量策略"
        assert entry.description == "测试"
        assert "动量有效" in entry.body

    def test_add_updates_index(self, mem):
        mem.add("A", "content A", type="project", description="desc A")
        mem.add("B", "content B", type="project", description="desc B")

        index_text = (mem._dir / "MEMORY.md").read_text(encoding="utf-8")
        assert "A" in index_text
        assert "B" in index_text
        assert "desc A" in index_text

    def test_add_overwrite_same_name(self, mem):
        mem.add("同名", "old content", type="project")
        mem.add("同名", "new content", type="project")

        entry = mem.find("同名")
        assert entry is not None
        assert "new content" in entry.body
        # Should only have one file
        md_files = [p for p in mem._dir.glob("*.md") if p.name != "MEMORY.md"]
        assert len(md_files) == 1

    def test_remove(self, mem):
        mem.add("删除我", "content", type="project")
        assert mem.remove("删除我") is True
        assert mem.find("删除我") is None

    def test_find_relevant(self, mem):
        mem.add("动量策略", "动量反转边界条件", type="project", description="动量相关")
        mem.add("价值因子", "PE PB 估值", type="project", description="价值相关")

        results = mem.find_relevant("动量")
        assert len(results) == 1
        assert results[0].title == "动量策略"

    def test_find_relevant_metadata_weight(self, mem):
        # body-only match should lose to metadata match
        mem.add("A", "动量策略细节", type="project", description="一般描述")
        mem.add("B", "其他内容", type="project", description="动量策略最佳实践")

        results = mem.find_relevant("动量策略")
        # B has metadata match (description), A has body match
        # Both should appear, B first due to metadata weight
        assert results[0].title == "B"
        assert results[1].title == "A"

    def test_list_entries(self, mem):
        mem.add("Z", "z", type="project")
        mem.add("A", "a", type="project")
        entries = mem.list_entries()
        assert len(entries) == 2
        # Should be sorted by filename
        assert entries[0].title == "A"
        assert entries[1].title == "Z"

    def test_snapshot(self, mem):
        mem.add("快照测试", "内容", type="project", description="desc")
        snap = mem.snapshot
        assert "快照测试" in snap
        assert "desc" in snap

    def test_sanitize_control_chars(self, mem):
        mem.add("控制字符", "body\x00\x01with\x1fcontrols", type="project")
        entry = mem.find("控制字符")
        assert "\x00" not in entry.body
        assert "with" in entry.body

    def test_truncate_long_body(self, mem):
        long_content = "x" * 10000
        mem.add("长文", long_content, type="project")
        entry = mem.find("长文")
        assert len(entry.body) <= 8000
        assert "[truncated at 8000 chars]" in entry.body
```

- [ ] **Step 2: Run tests**

```bash
cd /Users/yihaoyang/VScode\ workspace/quant-cluster
python3 -m pytest tests/memory/test_persistent.py -v
```
Expected: All 15 tests pass.

- [ ] **Step 3: Commit**

```bash
git add tests/memory/test_persistent.py
git commit -m "test(memory): add unit tests for PersistentMemory"
```

---

## Task 4: Orchestrator Recall Injection

**Files:**
- Modify: `orchestrator/core/orchestrator.py`

**Context:** In `_execute_agent()`, before sending the prompt to the Agent, query memory for entries relevant to the topic and append them to the system prompt.

---

- [ ] **Step 1: Modify `_execute_agent()` in `orchestrator/core/orchestrator.py`**

Find the existing code block (~line 361):

```python
        system_prompt = _read_soul(agent_name)
        user_prompt = DAG[agent_name]["prompt_template"].format(topic=topic)
```

Replace with:

```python
        system_prompt = _read_soul(agent_name)
        user_prompt = DAG[agent_name]["prompt_template"].format(topic=topic)

        # --- Memory recall injection ---
        try:
            from memory.persistent import PersistentMemory
            mem = PersistentMemory()
            relevant = mem.find_relevant(topic, max_results=3)
            if relevant:
                memory_lines = [
                    f"[历史研究记忆 #{i+1}] {e.title} — {e.description}"
                    for i, e in enumerate(relevant)
                ]
                # Append body preview for top result only to keep prompt compact
                if relevant[0].body:
                    preview = relevant[0].body.replace("\n", " ")[:300]
                    memory_lines.append(f"  摘要: {preview}...")

                memory_block = "\n".join(memory_lines)
                system_prompt += (
                    "\n\n---\n"
                    "以下历史研究可能与当前任务相关，请避免重复已知错误、复用有效方法。"
                    f"\n{memory_block}\n"
                )
        except Exception:
            # Memory is best-effort; never block Agent execution
            pass
```

- [ ] **Step 2: Verify import works in orchestrator context**

```bash
cd /Users/yihaoyang/VScode\ workspace/quant-cluster
python3 -c "from orchestrator.core.orchestrator import InteractiveOrchestrator; print('OK')"
```
Expected: `OK` (no import errors)

- [ ] **Step 3: Commit**

```bash
git add orchestrator/core/orchestrator.py
git commit -m "feat(orchestrator): inject relevant memory into Agent system prompt"
```

---

## Task 5: Agent SOUL.md Recall Instructions

**Files:**
- Modify: `agent_configs/hypothesis/SOUL.md`
- Modify: `agent_configs/data_engineer/SOUL.md`
- Modify: `agent_configs/quant_analyst/SOUL.md`
- Modify: `agent_configs/risk_auditor/SOUL.md`
- Modify: `agent_configs/strategy_writer/SOUL.md`

**Context:** Add a short section to each SOUL.md telling the Agent how to use injected historical memory. The section should be placed early in the document (after "角色定义" or "触发条件").

---

- [ ] **Step 1: Update `agent_configs/hypothesis/SOUL.md`**

Find the first `## ` heading after frontmatter. Add before or after it:

```markdown
## 历史研究参考

如果上下文中有 [历史研究记忆] 区块，请：
1. 阅读相关记忆，理解之前同类研究的核心假设和结论
2. 避免提出已被证伪的假设
3. 如记忆中有有效的经济学直觉或文献方向，优先复用或延伸
4. 在产出末尾增加一段「与历史研究的关系」：说明本假设是延续、修正、还是独立于之前的研究
```

- [ ] **Step 2: Update `agent_configs/data_engineer/SOUL.md`**

Add section:

```markdown
## 历史研究参考

如果上下文中有 [历史研究记忆] 区块，请：
1. 检查之前同类研究使用的数据源和特征工程方法
2. 优先复用已验证有效的数据配置（如 run_card 中记录的数据源）
3. 避免重复已知的数据质量问题（如某数据源在特定时间段缺失）
4. 在 data_quality_report 中引用历史研究的对比基线
```

- [ ] **Step 3: Update `agent_configs/quant_analyst/SOUL.md`**

Add section:

```markdown
## 历史研究参考

如果上下文中有 [历史研究记忆] 区块，请：
1. 查看之前同类策略的回测指标（Sharpe、最大回撤、胜率等）
2. 避免重复测试已被证伪的策略变体
3. 如记忆中有有效的参数范围或引擎配置，优先作为基线对比
4. 在 backtest_report 中明确标注「与历史策略的对比」
```

- [ ] **Step 4: Update `agent_configs/risk_auditor/SOUL.md`**

Add section:

```markdown
## 历史研究参考

如果上下文中有 [历史研究记忆] 区块，请：
1. 查看之前同类研究的审计结论（GO/NO-GO）和过拟合诊断
2. 对比当前结果与历史结果的稳定性指标（如参数稳定性 CV）
3. 如历史研究曾因某类风险被否，当前研究需明确说明是否已规避
4. 在 go_no_go_verdict 中引用历史审计作为参考基线
```

- [ ] **Step 5: Update `agent_configs/strategy_writer/SOUL.md`**

Add section:

```markdown
## 历史研究参考

如果上下文中有 [历史研究记忆] 区块，请：
1. 查看之前同类策略的 SOP 和失败分析
2. 如当前为 GO，对比历史 GO 策略的实盘注意事项
3. 如当前为 NO-GO，参考历史 NO-GO 的改进建议是否已被采纳
4. 在 trading_sop 或 strategy_failure_analysis 末尾增加「历史版本对比」章节
```

- [ ] **Step 6: Validate all SOUL.md files**

```bash
cd /Users/yihaoyang/VScode\ workspace/quant-cluster
python3 scripts/validate.py
```
Expected: `OK — all checks passed.`

- [ ] **Step 7: Commit**

```bash
git add agent_configs/
git commit -m "feat(agents): add historical memory recall instructions to all 5 SOUL.md"
```

---

## Task 6: Skill Update — Memory Extraction Section

**Files:**
- Modify: `.kimi/skills/quant-cluster/SKILL.md`

**Context:** Add a "Memory 管理" section to the existing skill, guiding Kimi Code to extract memory after pipeline completion.

---

- [ ] **Step 1: Append section to `.kimi/skills/quant-cluster/SKILL.md`**

Add before the final `## 全局约束` or after `## 最优运行实例`:

```markdown
## Memory 管理（Pipeline 完成后执行）

每次 pipeline 成功完成后，提取关键发现写入长期记忆，供后续 run 自动 recall。

### 提取流程

1. 定位最新 archive：
   ```bash
   ls -t shared_workspace/archive/ | head -1
   ```

2. **优先读取 run_card.json**（结构化数据）：
   ```bash
   cat shared_workspace/archive/{run_id}/03_backtest/run_card.json
   ```
   关注字段：`metrics`（Sharpe、最大回撤等）、`backtest.engine`、`data_sources`、`warnings`。

3. **补充阅读定性报告**：
   - `01_hypothesis/hypothesis_*.md` → 核心假设
   - `04_risk/go_no_go_verdict.md` → 审计结论
   - `05_strategy/trading_sop_*.md` 或 `strategy_failure_analysis.md` → 最终结果

4. 生成 memory content（浓缩洞察，非全量报告）：
   ```markdown
   ## 核心假设
   - ...

   ## 关键发现
   - GO/NO-GO 结论 + 核心指标（来自 run_card）
   - ...

   ## 失败教训
   - ...（如有 warnings 或 NO-GO）

   ## 工具备注
   - backtest_engine: ...
   - data_source: ...
   - run_card_config_hash: ...
   ```

5. 写入记忆：
   ```bash
   python3 -m memory add \
       --name "{topic_slug}" \
       --content "$(cat memory_content.md)" \
       --type project \
       --description "一句话摘要（包含核心指标）"
   ```

6. 验证：
   ```bash
   python3 -m memory search "{topic_keyword}"
   ```

### 查询历史记忆

```bash
# 关键词搜索
python3 -m memory search "动量" --max-results 5

# 列出全部
python3 -m memory list

# 查看单条
python3 -m memory show "动量与反转的边界条件"
```

### 注意事项

- Memory 存储在 `~/.quant-cluster/memory/`（用户级），跨项目共享
- 同名主题会**覆盖更新**，不会生成重复文件
- description 字段用于检索评分（metadata 权重 2.0），务必写清楚核心结论
- CJK 搜索按字符级匹配，写关键词时无需考虑分词
```

- [ ] **Step 2: Commit**

```bash
git add .kimi/skills/quant-cluster/SKILL.md
git commit -m "feat(skill): add Memory management section to quant-cluster skill"
```

---

## Task 7: Integration Validation

**Files:**
- None (verification only)

---

- [ ] **Step 1: Run full memory test suite**

```bash
cd /Users/yihaoyang/VScode\ workspace/quant-cluster
python3 -m pytest tests/memory/test_persistent.py -v
```
Expected: All tests pass.

- [ ] **Step 2: Run existing project tests**

```bash
cd /Users/yihaoyang/VScode\ workspace/quant-cluster
python3 -m pytest backtest/tests/ tests/data_router/ tests/monitor/ -v --tb=short
```
Expected: No regressions. (memory changes should not affect existing tests)

- [ ] **Step 3: Run validation script**

```bash
python3 scripts/validate.py
```
Expected: `OK — all checks passed.`

- [ ] **Step 4: End-to-end smoke test (manual)**

```bash
# 1. Add a test memory
python3 -m memory add --name "烟雾测试" --content "## 假设\n烟雾测试通过" --type project --description "测试 memory 系统"

# 2. Search it
python3 -m memory search "烟雾"
# Expected: Shows "烟雾测试"

# 3. List it
python3 -m memory list
# Expected: Shows "烟雾测试"

# 4. Show it
python3 -m memory show "烟雾测试"
# Expected: Shows full content

# 5. Clean up test memory
python3 -m memory remove "烟雾测试" 2>/dev/null || true
```

- [ ] **Step 5: Final commit**

```bash
git commit --allow-empty -m "feat(memory): complete memory system implementation"
```

---

## Spec Coverage Check

| Spec Section | Implementing Task |
|--------------|-------------------|
| 3.1 Memory Entry 文件格式 | Task 1 (`persistent.py` frontmatter) |
| 3.2 MEMORY.md 索引 | Task 1 (`_update_index`, `_rebuild_index`) |
| 3.3 存储目录 | Task 1 (`MEMORY_BASE`) |
| 4.1 Agent Recall 注入点 | Task 4 (`orchestrator.py`) |
| 4.2 注入策略 | Task 4 (max_results=3, body[:300]) |
| 4.3 Agent SOUL.md 更新 | Task 5 (5 files) |
| 5.2 `persistent.py` 核心类 | Task 1 |
| 5.3 Tokenization | Task 1 (`_tokenize`) |
| 5.4 CLI 接口 | Task 2 (`__main__.py`) |
| 6.2 Skill 提取流程 | Task 6 (Skill.md) |
| 7.2 为什么不自动化提取 | Documented in spec, Skill guides manual extraction |

---

## Placeholder Scan

- No "TBD", "TODO", "implement later"
- No vague "add error handling" steps
- All test code is complete
- All file paths are exact
- All commands include expected output
