import sys
from pathlib import Path

SKILL_SCRIPTS = Path(__file__).parent.parent.parent / "agent_configs" / "paper_manager" / "skills" / "paper-scanning" / "scripts"
sys.path.insert(0, str(SKILL_SCRIPTS))

import pytest
import fitz

from slice_pdf import extract_text_blocks_with_fonts, extract_title, identify_sections, extract_section, extract_all_figures, extract_structured_tables, contains_keywords, slice_pdf


class TestExtractTextBlocks:
    def test_returns_list_of_dicts(self, sample_pdf):
        doc = fitz.open(str(sample_pdf))
        try:
            blocks = extract_text_blocks_with_fonts(doc)
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
        finally:
            doc.close()


class TestExtractTitle:
    def test_extracts_non_empty_title(self, sample_pdf):
        doc = fitz.open(str(sample_pdf))
        try:
            blocks = extract_text_blocks_with_fonts(doc)
            title = extract_title(blocks)
            assert isinstance(title, str)
            assert len(title) > 0
            assert title.lower() not in {"abstract", "introduction", "keywords", "jel classification"}
        finally:
            doc.close()


class TestIdentifySections:
    def test_identifies_known_sections(self, sample_pdf):
        doc = fitz.open(str(sample_pdf))
        try:
            blocks = extract_text_blocks_with_fonts(doc)
            sections = identify_sections(blocks)
            assert isinstance(sections, dict)
            # At least one known section should be found (abstract, introduction, references, etc.)
            found = {k.lower() for k in sections.keys()}
            assert "abstract" in found or "introduction" in found or "references" in found, f"Expected a known section in {found}"
        finally:
            doc.close()


class TestExtractSection:
    def test_extracts_abstract_text(self, sample_pdf):
        doc = fitz.open(str(sample_pdf))
        try:
            blocks = extract_text_blocks_with_fonts(doc)
            sections = identify_sections(blocks)
            text = extract_section(sections, "abstract")
            assert isinstance(text, str)
            if text:
                assert len(text) > 20, f"Abstract text too short: {text!r}"
        finally:
            doc.close()

    def test_extracts_references_text(self, sample_pdf):
        doc = fitz.open(str(sample_pdf))
        try:
            blocks = extract_text_blocks_with_fonts(doc)
            sections = identify_sections(blocks)
            text = extract_section(sections, "references")
            assert isinstance(text, str)
            assert len(text) > 20, f"References text too short: {text!r}"
            assert "Alexakis" in text or "Bouri" in text
        finally:
            doc.close()


class TestExtractAllFigures:
    def test_extracts_figures_to_files(self, sample_pdf, scanned_dir):
        import shutil
        output_dir = scanned_dir / "test_figures"
        output_dir.mkdir(parents=True, exist_ok=True)
        
        doc = fitz.open(str(sample_pdf))
        try:
            figures = extract_all_figures(doc, output_dir)
            assert isinstance(figures, list)
            if len(figures) > 0:
                for fig in figures:
                    assert "path" in fig
                    assert "page_num" in fig
                    assert Path(fig["path"]).exists()
                    assert Path(fig["path"]).stat().st_size > 100
        finally:
            doc.close()
            # Cleanup
            if output_dir.exists():
                shutil.rmtree(output_dir)


class TestExtractStructuredTables:
    def test_returns_list_of_tables(self, sample_pdf):
        doc = fitz.open(str(sample_pdf))
        try:
            tables = extract_structured_tables(doc)
            assert isinstance(tables, list)
            for table in tables:
                assert "headers" in table
                assert "rows" in table
                assert "page_num" in table
                assert isinstance(table["headers"], list)
                assert isinstance(table["rows"], list)
                assert isinstance(table["page_num"], int)
        finally:
            doc.close()


class TestContainsKeywords:
    def test_detects_quant_keywords(self):
        blocks = [
            {"text": "This paper uses regression analysis and Sharpe ratio."},
            {"text": "We calculate alpha and beta for the portfolio."},
        ]
        keywords = ["regression", "sharpe ratio", "alpha", "beta", "portfolio"]
        assert contains_keywords(blocks, keywords, threshold=2) is True

    def test_no_false_positives(self):
        blocks = [
            {"text": "This is a qualitative study about market sentiment."},
            {"text": "We interviewed participants about their opinions."},
        ]
        keywords = ["regression", "sharpe ratio", "alpha", "beta", "portfolio"]
        assert contains_keywords(blocks, keywords, threshold=2) is False


class TestSlicePdf:
    def test_returns_complete_content_package(self, sample_pdf, scanned_dir):
        import shutil
        output_dir = scanned_dir / "test_slice"
        if output_dir.exists():
            shutil.rmtree(output_dir)
        
        result = slice_pdf(sample_pdf, output_dir=output_dir)
        
        assert isinstance(result, dict)
        assert "doc_id" in result
        assert "filepath" in result
        assert "core" in result
        assert "empirical" in result
        assert "proofs" in result
        assert "is_likely_quant" in result
        
        core = result["core"]
        assert "title" in core
        assert "abstract" in core
        assert "intro" in core
        assert "conclusions" in core
        assert "figures" in core
        assert "figure_captions" in core
        assert "tables" in core
        
        if core["figures"]:
            for fig in core["figures"]:
                assert "path" in fig
