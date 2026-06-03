import sys
from pathlib import Path

SKILL_SCRIPTS = Path(__file__).parent.parent.parent / "agent_configs" / "paper_manager" / "skills" / "paper-scanning" / "scripts"
sys.path.insert(0, str(SKILL_SCRIPTS))

import json
import pytest
from build_index import build_index


class TestBuildIndex:
    def test_builds_index_from_scan_state(self, tmp_path):
        scan_state = {
            "last_updated": "2026-06-01T00:00:00Z",
            "papers": {
                "journal_001": {
                    "filepath": "raw/journal/j1.pdf",
                    "status": "completed",
                    "paper_type": "quantitative",
                    "source_tier": "journal",
                    "scanned_at": "2026-06-01T10:00:00Z",
                    "card_data": {
                        "title": "Journal Paper",
                        "authors": ["Alice", "Bob"],
                        "year": 2024,
                        "source": "elsevier",
                        "credibility_score": 85,
                        "credibility_tier": "green",
                        "quant_summary": {"best_sharpe": 1.2}
                    }
                },
                "arxiv_001": {
                    "filepath": "raw/arxiv/a1.pdf",
                    "status": "completed",
                    "paper_type": "theoretical",
                    "source_tier": "arxiv",
                    "scanned_at": "2026-06-01T11:00:00Z",
                    "card_data": {
                        "title": "ArXiv Paper",
                        "authors": ["Carol"],
                        "year": 2025,
                        "source": "arxiv",
                        "credibility_score": 60,
                        "credibility_tier": "yellow"
                    }
                },
                "pending_001": {
                    "filepath": "raw/ssrn/p1.pdf",
                    "status": "pending"
                }
            }
        }
        scan_state_path = tmp_path / "scan_state.json"
        scan_state_path.write_text(json.dumps(scan_state))
        output_path = tmp_path / "index.json"

        build_index(scan_state_path, output_path)

        index = json.loads(output_path.read_text())
        assert "last_updated" in index
        assert index["total_scanned"] == 2
        assert index["by_tier"]["journal"] == 1
        assert index["by_tier"]["arxiv"] == 1
        assert index["by_type"]["quantitative"] == 1
        assert index["by_type"]["theoretical"] == 1

        papers = index["papers"]
        assert len(papers) == 2
        # journal should come before arxiv
        assert papers[0]["doc_id"] == "journal_001"
        assert papers[1]["doc_id"] == "arxiv_001"

        # Check entry fields
        entry = papers[0]
        assert entry["title"] == "Journal Paper"
        assert entry["authors"] == ["Alice", "Bob"]
        assert entry["year"] == 2024
        assert entry["source"] == "elsevier"
        assert entry["source_tier"] == "journal"
        assert entry["paper_type"] == "quantitative"
        assert entry["credibility_score"] == 85
        assert entry["credibility_tier"] == "green"
        assert entry["card_paths"]["zh"] == "scanned/journal_001/card.md"
        assert entry["card_paths"]["en"] == "scanned/journal_001/card_en.md"
        assert entry["quant_summary"]["best_sharpe"] == 1.2
