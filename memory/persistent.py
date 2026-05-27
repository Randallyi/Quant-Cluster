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
    text = text.replace("_", " ")
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
        """Return the current index content (first 200 lines), re-read from disk."""
        if self._index_path.exists():
            try:
                text = self._index_path.read_text(encoding="utf-8")
                lines = text.split("\n")[:MAX_INDEX_LINES]
                return "\n".join(lines)
            except OSError:
                return ""
        return ""

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
