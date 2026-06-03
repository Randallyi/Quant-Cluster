import pytest
from pathlib import Path

@pytest.fixture
def fixtures_dir() -> Path:
    return Path(__file__).parent / "fixtures"

@pytest.fixture
def sample_pdf(fixtures_dir: Path) -> Path:
    pdf = fixtures_dir / "sample_paper.pdf"
    assert pdf.exists(), f"Sample PDF not found: {pdf}"
    return pdf

@pytest.fixture
def scanned_dir() -> Path:
    root = Path(__file__).parent.parent.parent / "shared_workspace" / "papers" / "scanned"
    return root
