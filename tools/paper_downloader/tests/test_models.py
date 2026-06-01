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


def test_suggested_filename_with_special_chars():
    meta = PaperMeta(source="core", source_id="abc:123/456")
    assert meta.suggested_filename() == "core_abc_123_456.pdf"


def test_unique_key_doi_lowercase():
    meta = PaperMeta(source="core", source_id="123", doi="10.1234/TEST")
    assert meta.unique_key() == "10.1234/test"


def test_unique_key_whitespace_doi():
    meta = PaperMeta(source="core", source_id="456", doi="   ")
    assert meta.unique_key() == "core:456"


def test_authors_defaults_to_none():
    meta = PaperMeta(source="core", source_id="789")
    assert meta.authors is None
