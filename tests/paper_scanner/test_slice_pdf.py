import sys
from pathlib import Path

SKILL_SCRIPTS = Path(__file__).parent.parent.parent / "agent_configs" / "paper_manager" / "skills" / "paper-scanning" / "scripts"
sys.path.insert(0, str(SKILL_SCRIPTS))

import pytest
import fitz

from slice_pdf import extract_text_blocks_with_fonts, extract_title


@pytest.fixture
def sample_pdf():
    fixture_path = Path(__file__).parent / "fixtures" / "sample_paper.pdf"
    return fitz.open(str(fixture_path))


class TestExtractTextBlocks:
    def test_returns_list_of_dicts(self, sample_pdf):
        blocks = extract_text_blocks_with_fonts(sample_pdf)
        assert isinstance(blocks, list)
        assert len(blocks) > 0
        for block in blocks:
            assert "text" in block
            assert "font_size" in block
            assert "page_num" in block
            assert "bbox" in block
            assert isinstance(block["text"], str)
            assert isinstance(block["font_size"], float)
            assert isinstance(block["page_num"], int)


class TestExtractTitle:
    def test_extracts_non_empty_title(self, sample_pdf):
        blocks = extract_text_blocks_with_fonts(sample_pdf)
        title = extract_title(blocks)
        assert isinstance(title, str)
        assert len(title) > 0
        assert title.lower() not in {"abstract", "introduction", "keywords", "jel classification"}
