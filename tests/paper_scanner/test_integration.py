import json
import shutil
import sys
from pathlib import Path

SKILL_SCRIPTS = (
    Path(__file__).parent.parent.parent
    / "agent_configs"
    / "paper_manager"
    / "skills"
    / "paper-scanning"
    / "scripts"
)
sys.path.insert(0, str(SKILL_SCRIPTS))

import fitz
import pytest

from build_index import build_index
from scan_state import ScanState
from slice_pdf import slice_pdf
from verify_card import verify_card


class TestEndToEnd:
    def test_full_pipeline(self, sample_pdf, tmp_path):
        # 1. Slice PDF
        output_dir = tmp_path / "scanned" / "sample_paper" / "figures"
        result = slice_pdf(sample_pdf, output_dir=output_dir)

        assert "doc_id" in result
        assert "core" in result
        assert "empirical" in result
        assert "proofs" in result
        assert output_dir.exists()

        doc_id = result["doc_id"]

        # 2. Create a mock card
        card_dir = output_dir.parent
        card_dir.mkdir(parents=True, exist_ok=True)
        card_path = card_dir / "card.md"

        card_content = (
            "---\n"
            f"doc_id: {doc_id}\n"
            "title: Sample Paper for Integration Test\n"
            "authors: [Test Author]\n"
            "year: 2024\n"
            "source: test\n"
            "source_tier: journal\n"
            "paper_type: quantitative\n"
            "---\n\n"
            "## 量化深度分析\n"
            "This paper analyzes quantitative strategies.\n\n"
            "## 方法论可信度评分\n"
            "Score: 85/100.\n\n"
            "## 可迁移性评估\n"
            "High transferability to US equities.\n\n"
            "## 因子与回测\n"
            "Sharpe ratio of 1.2 over 10 years.\n\n"
            "## 关键发现\n"
            "Momentum factor is significant.\n\n"
            "## 方法论风险\n"
            "Look-ahead bias possible.\n"
        )
        card_path.write_text(card_content, encoding="utf-8")

        # 3. Verify card
        verification = verify_card(card_path)
        assert verification == {"valid": True, "errors": []}

        # 4. Update scan state
        state_path = tmp_path / "scan_state.json"
        state = ScanState(state_path)
        state.add_paper(str(sample_pdf), doc_id)
        state.mark_status(
            doc_id,
            "completed",
            card_data={
                "title": "Sample Paper for Integration Test",
                "authors": ["Test Author"],
                "year": 2024,
                "source": "test",
                "source_tier": "journal",
                "paper_type": "quantitative",
                "credibility_score": 85,
                "credibility_tier": "green",
            },
            scanned_at="2026-06-03T00:00:00Z",
        )

        # 5. Build index
        index_path = tmp_path / "index.json"
        build_index(state_path, index_path)

        index = json.loads(index_path.read_text(encoding="utf-8"))
        assert index["total_scanned"] == 1
        assert any(p["doc_id"] == doc_id for p in index["papers"])

        # Cleanup temp directories
        if tmp_path.exists():
            shutil.rmtree(tmp_path)
