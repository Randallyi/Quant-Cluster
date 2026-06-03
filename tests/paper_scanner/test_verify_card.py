import sys
from pathlib import Path

SKILL_SCRIPTS = Path(__file__).parent.parent.parent / "agent_configs" / "paper_manager" / "skills" / "paper-scanning" / "scripts"
sys.path.insert(0, str(SKILL_SCRIPTS))

import pytest
from verify_card import parse_frontmatter, verify_card


class TestParseFrontmatter:
    def test_parses_valid_frontmatter(self, tmp_path):
        card = tmp_path / "card.md"
        card.write_text(
            "---\n"
            "doc_id: test_123\n"
            "title: Test Paper\n"
            "authors: [Alice, Bob]\n"
            "year: 2024\n"
            "source: elsevier\n"
            "source_tier: journal\n"
            "paper_type: quantitative\n"
            "---\n\n"
            "## 量化深度分析\n"
            "some content\n"
        )
        result = parse_frontmatter(card)
        assert result["doc_id"] == "test_123"
        assert result["title"] == "Test Paper"
        assert result["authors"] == ["Alice", "Bob"]
        assert result["year"] == 2024


class TestVerifyCard:
    def test_validates_required_fields(self, tmp_path):
        card = tmp_path / "card.md"
        card.write_text(
            "---\n"
            "doc_id: test_123\n"
            "title: Test Paper\n"
            "authors: [Alice]\n"
            "year: 2024\n"
            "source: elsevier\n"
            "---\n\n"
            "some content\n"
        )
        result = verify_card(card)
        assert result["valid"] is False
        assert any("source_tier" in e for e in result["errors"])
        assert any("paper_type" in e for e in result["errors"])

    def test_validates_quant_sections(self, tmp_path):
        card = tmp_path / "card.md"
        card.write_text(
            "---\n"
            "doc_id: test_123\n"
            "title: Test Paper\n"
            "authors: [Alice]\n"
            "year: 2024\n"
            "source: elsevier\n"
            "source_tier: journal\n"
            "paper_type: quantitative\n"
            "---\n\n"
            "## 基础分析\n"
            "some content\n"
        )
        result = verify_card(card)
        assert result["valid"] is False
        assert any("量化深度分析" in e for e in result["errors"])
        assert any("方法论可信度评分" in e for e in result["errors"])
