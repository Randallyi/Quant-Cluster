import sys
from pathlib import Path

SKILL_SCRIPTS = Path(__file__).parent.parent.parent / "agent_configs" / "paper_manager" / "skills" / "paper-scanning" / "scripts"
sys.path.insert(0, str(SKILL_SCRIPTS))

import json
import pytest
from scan_state import ScanState


class TestScanState:
    def test_creates_new_state_if_not_exists(self, tmp_path):
        state_path = tmp_path / "scan_state.json"
        state = ScanState(state_path)
        assert state.data["total_papers"] == 0
        assert state.data["stats"]["pending"] == 0
        assert state.data["stats"]["completed"] == 0
        assert state.data["config"]["max_concurrent"] == 3
        assert state_path.exists()

    def test_adds_and_updates_paper(self, tmp_path):
        state_path = tmp_path / "scan_state.json"
        state = ScanState(state_path)
        state.add_paper("raw/journal/test.pdf", "doc_001")
        assert state.data["total_papers"] == 1
        assert state.data["papers"]["doc_001"]["status"] == "pending"
        assert state.data["stats"]["pending"] == 1

        state.mark_status("doc_001", "completed", paper_type="quantitative")
        assert state.data["papers"]["doc_001"]["status"] == "completed"
        assert state.data["papers"]["doc_001"]["paper_type"] == "quantitative"
        assert state.data["stats"]["pending"] == 0
        assert state.data["stats"]["completed"] == 1

    def test_gets_pending_queue(self, tmp_path):
        state_path = tmp_path / "scan_state.json"
        state = ScanState(state_path)
        state.add_paper("raw/journal/j1.pdf", "journal_001")
        state.mark_status("journal_001", "pending", source_tier="journal", year=2023)

        state.add_paper("raw/arxiv/a1.pdf", "arxiv_001")
        state.mark_status("arxiv_001", "pending", source_tier="arxiv", year=2024)

        state.add_paper("raw/ssrn/s1.pdf", "ssrn_001")
        state.mark_status("ssrn_001", "pending", source_tier="ssrn", year=2022)

        pending = state.get_pending()
        assert len(pending) == 3
        # journal > ssrn > arxiv
        assert pending[0]["doc_id"] == "journal_001"
        assert pending[1]["doc_id"] == "ssrn_001"
        assert pending[2]["doc_id"] == "arxiv_001"
