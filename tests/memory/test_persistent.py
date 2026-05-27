"""Unit tests for memory.persistent."""

import tempfile
from pathlib import Path

import pytest

from memory.persistent import PersistentMemory, _tokenize, _parse_frontmatter, _coerce_str


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


class TestCoerceStr:
    def test_string(self):
        assert _coerce_str("hello") == "hello"

    def test_none(self):
        assert _coerce_str(None) == ""

    def test_none_with_default(self):
        assert _coerce_str(None, default="fallback") == "fallback"

    def test_bool_true(self):
        assert _coerce_str(True) == "true"

    def test_bool_false(self):
        assert _coerce_str(False) == "false"

    def test_list(self):
        assert _coerce_str(["a", "b", 1]) == "a, b, 1"


class TestPersistentMemory:
    @pytest.fixture
    def mem(self, tmp_path):
        return PersistentMemory(memory_dir=tmp_path)

    def test_add_and_find(self, mem):
        path = mem.add("动量策略", "## 假设\n动量有效", memory_type="project", description="测试")
        assert path.exists()

        entry = mem.find("动量策略")
        assert entry is not None
        assert entry.title == "动量策略"
        assert entry.description == "测试"
        assert "动量有效" in entry.body

    def test_add_updates_index(self, mem):
        mem.add("A", "content A", memory_type="project", description="desc A")
        mem.add("B", "content B", memory_type="project", description="desc B")

        index_text = (mem._dir / "MEMORY.md").read_text(encoding="utf-8")
        assert "A" in index_text
        assert "B" in index_text
        assert "desc A" in index_text

    def test_add_overwrite_same_name(self, mem):
        mem.add("同名", "old content", memory_type="project")
        mem.add("同名", "new content", memory_type="project")

        entry = mem.find("同名")
        assert entry is not None
        assert "new content" in entry.body
        # Should only have one file
        md_files = [p for p in mem._dir.glob("*.md") if p.name != "MEMORY.md"]
        assert len(md_files) == 1

    def test_remove(self, mem):
        mem.add("删除我", "content", memory_type="project")
        assert mem.remove("删除我") is True
        assert mem.find("删除我") is None

    def test_find_relevant(self, mem):
        mem.add("动量策略", "动量反转边界条件", memory_type="project", description="动量相关")
        mem.add("价值因子", "PE PB 估值", memory_type="project", description="价值相关")

        results = mem.find_relevant("动量")
        assert len(results) == 1
        assert results[0].title == "动量策略"

    def test_find_relevant_metadata_weight(self, mem):
        # body-only match should lose to metadata match
        mem.add("A", "动量策略细节", memory_type="project", description="一般描述")
        mem.add("B", "其他内容", memory_type="project", description="动量策略最佳实践")

        results = mem.find_relevant("动量策略")
        # B has metadata match (description), A has body match
        # Both should appear, B first due to metadata weight
        assert results[0].title == "B"
        assert results[1].title == "A"

    def test_list_entries(self, mem):
        mem.add("Z", "z", memory_type="project")
        mem.add("A", "a", memory_type="project")
        entries = mem.list_entries()
        assert len(entries) == 2
        # Should be sorted by filename
        assert entries[0].title == "A"
        assert entries[1].title == "Z"

    def test_snapshot(self, mem):
        mem.add("快照测试", "内容", memory_type="project", description="desc")
        snap = mem.snapshot
        assert "快照测试" in snap
        assert "desc" in snap

    def test_sanitize_control_chars(self, mem):
        mem.add("控制字符", "body\x00\x01with\x1fcontrols", memory_type="project")
        entry = mem.find("控制字符")
        assert "\x00" not in entry.body
        assert "with" in entry.body

    def test_truncate_long_body(self, mem):
        long_content = "x" * 10000
        mem.add("长文", long_content, memory_type="project")
        entry = mem.find("长文")
        assert len(entry.body) <= 8000
        assert "[truncated at 8000 chars]" in entry.body

    def test_find_by_stem_fallback(self, mem):
        mem.add("测试标题", "body", memory_type="project")
        entry = mem.find("project_测试标题")
        assert entry is not None
        assert entry.title == "测试标题"

    def test_remove_returns_false_when_not_found(self, mem):
        assert mem.remove("不存在的记忆") is False

    def test_find_relevant_empty_query(self, mem):
        mem.add("测试", "内容", memory_type="project")
        assert mem.find_relevant("") == []
        assert mem.find_relevant("   ") == []

    def test_find_returns_none_for_empty_name(self, mem):
        assert mem.find("") is None
        assert mem.find("   ") is None
