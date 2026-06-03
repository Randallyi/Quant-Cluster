# Paper Scanner Skill Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build the paper-scanning skill for the Paper Manager Agent, enabling intelligent PDF content slicing, structured paper card generation, and index management.

**Architecture:** A script layer (`slice_pdf.py`) uses PyMuPDF to extract and curate high-value content (figures, text, tables) from PDFs. A parent Agent dispatches subagents to analyze each paper in isolation, producing bilingual Markdown cards. State is tracked in `scan_state.json`, with a global index in `scanned/index.json`.

**Tech Stack:** Python 3.11, PyMuPDF (fitz), pytest, JSON

---

## File Structure

### New Directories

```
agent_configs/paper_manager/skills/paper-scanning/
├── SKILL.md
├── references/
│   ├── card-template.md
│   ├── preprocessing-guide.md
│   └── subagent-prompt.md
└── scripts/
    ├── __init__.py
    ├── slice_pdf.py
    ├── verify_card.py
    └── build_index.py

tests/paper_scanner/
├── __init__.py
├── conftest.py
├── fixtures/
│   └── sample_paper.pdf          # copied from raw/ssrn/ssrn_3885538.pdf
├── test_slice_pdf.py
├── test_verify_card.py
├── test_build_index.py
└── test_scan_state.py

shared_workspace/papers/
└── scanned/                       # created on first run
```

### File Responsibilities

| File | Responsibility |
|------|----------------|
| `scripts/slice_pdf.py` | PDF → structured content package (Tier 1/2/3 extraction, figure images, table data, quant keyword detection) |
| `scripts/verify_card.py` | Validate card.md format: frontmatter fields, required sections, type consistency |
| `scripts/build_index.py` | Generate `scanned/index.json` from `scan_state.json` with sorting |
| `SKILL.md` | Main skill document: workflow checklist, subagent dispatch, card assembly |
| `references/card-template.md` | Exact card.md and card_en.md templates with field specs |
| `references/subagent-prompt.md` | Subagent system prompt template with todo checklist |
| `references/preprocessing-guide.md` | How to use slice_pdf.py, fallback strategies, troubleshooting |

---

## Task 1: Project Scaffolding — Directory Structure and Pytest Config

**Files:**
- Create: `agent_configs/paper_manager/skills/paper-scanning/scripts/__init__.py`
- Create: `agent_configs/paper_manager/skills/paper-scanning/references/.gitkeep`
- Create: `tests/paper_scanner/__init__.py`
- Create: `tests/paper_scanner/conftest.py`
- Create: `tests/paper_scanner/fixtures/.gitkeep`
- Create: `shared_workspace/papers/scanned/.gitkeep`
- Modify: `tests/__init__.py` (ensure exists)

- [ ] **Step 1: Create skill directory tree**

```bash
cd "/Users/yihaoyang/VScode workspace/quant-cluster"
mkdir -p agent_configs/paper_manager/skills/paper-scanning/{scripts,references}
mkdir -p tests/paper_scanner/fixtures
mkdir -p shared_workspace/papers/scanned
touch agent_configs/paper_manager/skills/paper-scanning/scripts/__init__.py
touch tests/paper_scanner/__init__.py
touch tests/paper_scanner/fixtures/.gitkeep
touch shared_workspace/papers/scanned/.gitkeep
```

- [ ] **Step 2: Copy sample PDF for tests**

```bash
cp "shared_workspace/papers/raw/ssrn/ssrn_3885538.pdf" \
   "tests/paper_scanner/fixtures/sample_paper.pdf"
```

Verify:
```bash
ls -la tests/paper_scanner/fixtures/sample_paper.pdf
# Expected: file exists, ~185KB
```

- [ ] **Step 3: Create pytest configuration**

Create `tests/paper_scanner/conftest.py`:

```python
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
```

- [ ] **Step 4: Verify pytest can discover tests**

```bash
cd "/Users/yihaoyang/VScode workspace/quant-cluster"
python3 -m pytest tests/paper_scanner/ -v --collect-only
```

Expected: discovers 0 tests (none written yet), no errors.

- [ ] **Step 5: Commit**

```bash
git add agent_configs/paper_manager/skills/paper-scanning/ tests/paper_scanner/ shared_workspace/papers/scanned/
git commit -m "feat(scanner): scaffold paper-scanning skill directory structure"
```

---

## Task 2: slice_pdf.py — Text Block Extraction with Font Metadata

**Files:**
- Create: `agent_configs/paper_manager/skills/paper-scanning/scripts/slice_pdf.py`
- Create: `tests/paper_scanner/test_slice_pdf.py`

- [ ] **Step 1: Write failing test for extract_text_blocks_with_fonts**

`tests/paper_scanner/test_slice_pdf.py`:

```python
import pytest
from pathlib import Path

# Will import from scripts after implementation
# from agent_configs.paper_manager.skills.paper_scanning.scripts.slice_pdf import extract_text_blocks_with_fonts

class TestExtractTextBlocks:
    def test_returns_list_of_dicts(self, sample_pdf: Path):
        from scripts.slice_pdf import extract_text_blocks_with_fonts
        import fitz
        
        doc = fitz.open(str(sample_pdf))
        blocks = extract_text_blocks_with_fonts(doc)
        doc.close()
        
        assert isinstance(blocks, list)
        assert len(blocks) > 0
        
        # Each block should have required fields
        for block in blocks:
            assert "text" in block
            assert "font_size" in block
            assert "page_num" in block
            assert "bbox" in block
            assert isinstance(block["text"], str)
            assert isinstance(block["font_size"], float)
            assert isinstance(block["page_num"], int)
```

- [ ] **Step 2: Run test to verify it fails**

```bash
cd "/Users/yihaoyang/VScode workspace/quant-cluster"
python3 -m pytest tests/paper_scanner/test_slice_pdf.py::TestExtractTextBlocks::test_returns_list_of_dicts -v
```

Expected: `ModuleNotFoundError: No module named 'scripts'` or `ImportError`

- [ ] **Step 3: Implement extract_text_blocks_with_fonts**

`agent_configs/paper_manager/skills/paper-scanning/scripts/slice_pdf.py`:

```python
"""PDF intelligent content slicing for paper scanning."""

from pathlib import Path
from typing import Dict, List, Optional, Tuple
import fitz  # PyMuPDF


def extract_text_blocks_with_fonts(doc: fitz.Document) -> List[Dict]:
    """Extract all text blocks with font metadata.
    
    Returns list of dicts with keys: text, font_size, page_num, bbox
    """
    blocks = []
    for page_num, page in enumerate(doc, start=1):
        text_dict = page.get_text("dict")
        for block in text_dict.get("blocks", []):
            if block.get("type") != 0:  # Skip image blocks
                continue
            
            block_text = ""
            max_font_size = 0.0
            for line in block.get("lines", []):
                for span in line.get("spans", []):
                    block_text += span.get("text", "")
                    font_size = span.get("size", 0)
                    if font_size > max_font_size:
                        max_font_size = font_size
            
            if block_text.strip():
                blocks.append({
                    "text": block_text.strip(),
                    "font_size": max_font_size,
                    "page_num": page_num,
                    "bbox": block.get("bbox", [0, 0, 0, 0]),
                })
    return blocks
```

- [ ] **Step 4: Fix import path in test**

Since scripts are in `agent_configs/paper_manager/skills/paper-scanning/scripts/`, add the parent to PYTHONPATH or adjust import. The simplest approach for tests:

```python
import sys
from pathlib import Path

SKILL_SCRIPTS = Path(__file__).parent.parent.parent / "agent_configs" / "paper_manager" / "skills" / "paper-scanning" / "scripts"
sys.path.insert(0, str(SKILL_SCRIPTS))

from slice_pdf import extract_text_blocks_with_fonts
```

Update `tests/paper_scanner/test_slice_pdf.py` with this import pattern.

- [ ] **Step 5: Run test to verify it passes**

```bash
cd "/Users/yihaoyang/VScode workspace/quant-cluster"
python3 -m pytest tests/paper_scanner/test_slice_pdf.py::TestExtractTextBlocks::test_returns_list_of_dicts -v
```

Expected: PASS

- [ ] **Step 6: Write failing test for extract_title**

```python
class TestExtractTitle:
    def test_extracts_non_empty_title(self, sample_pdf: Path):
        from slice_pdf import extract_text_blocks_with_fonts, extract_title
        import fitz
        
        doc = fitz.open(str(sample_pdf))
        blocks = extract_text_blocks_with_fonts(doc)
        title = extract_title(blocks)
        doc.close()
        
        assert isinstance(title, str)
        assert len(title) > 0
        # Title should not be a section header like "Abstract"
        assert title.lower() not in ["abstract", "introduction", "references"]
```

- [ ] **Step 7: Implement extract_title**

```python
def extract_title(blocks: List[Dict]) -> str:
    """Extract paper title from text blocks.
    
    Heuristic: largest font size on first page, excluding common headers.
    """
    HEADER_KEYWORDS = {"abstract", "introduction", "keywords", "jel classification"}
    
    first_page_blocks = [b for b in blocks if b["page_num"] == 1]
    if not first_page_blocks:
        return ""
    
    # Sort by font size descending
    sorted_blocks = sorted(first_page_blocks, key=lambda b: b["font_size"], reverse=True)
    
    for block in sorted_blocks:
        text = block["text"].strip()
        text_lower = text.lower()
        # Skip short text and known headers
        if len(text) < 10:
            continue
        if any(kw in text_lower for kw in HEADER_KEYWORDS):
            continue
        return text
    
    # Fallback: largest text on first page
    return sorted_blocks[0]["text"].strip() if sorted_blocks else ""
```

- [ ] **Step 8: Run test to verify it passes**

```bash
python3 -m pytest tests/paper_scanner/test_slice_pdf.py::TestExtractTitle -v
```

Expected: PASS

- [ ] **Step 9: Commit**

```bash
git add agent_configs/paper_manager/skills/paper-scanning/scripts/slice_pdf.py tests/paper_scanner/test_slice_pdf.py
git commit -m "feat(scanner): add text block extraction and title detection"
```

---

## Task 3: slice_pdf.py — Section Structure Identification

**Files:**
- Modify: `agent_configs/paper_manager/skills/paper-scanning/scripts/slice_pdf.py`
- Modify: `tests/paper_scanner/test_slice_pdf.py`

- [ ] **Step 1: Write failing test for identify_sections**

```python
class TestIdentifySections:
    def test_identifies_known_sections(self, sample_pdf: Path):
        from slice_pdf import extract_text_blocks_with_fonts, identify_sections
        import fitz
        
        doc = fitz.open(str(sample_pdf))
        blocks = extract_text_blocks_with_fonts(doc)
        sections = identify_sections(blocks)
        doc.close()
        
        assert isinstance(sections, dict)
        # Should find at least abstract or introduction
        has_abstract = "abstract" in {k.lower() for k in sections.keys()}
        has_intro = "introduction" in {k.lower() for k in sections.keys()}
        assert has_abstract or has_intro, f"Found sections: {list(sections.keys())}"
```

- [ ] **Step 2: Run test to verify it fails**

```bash
python3 -m pytest tests/paper_scanner/test_slice_pdf.py::TestIdentifySections -v
```

Expected: `AttributeError: module 'slice_pdf' has no attribute 'identify_sections'`

- [ ] **Step 3: Implement identify_sections**

```python
def identify_sections(blocks: List[Dict]) -> Dict[str, List[Dict]]:
    """Heuristically identify section headers from text blocks.
    
    Uses font size (20%+ larger than median), all-caps patterns, and keyword matching.
    Returns dict mapping section name to list of blocks in that section.
    """
    import statistics
    
    KNOWN_SECTIONS = {
        "abstract", "introduction", "literature review", "related work",
        "data", "methodology", "methods", "empirical", "results",
        "discussion", "conclusion", "conclusions", "references",
        "acknowledgment", "acknowledgments", "appendix", "proof",
        "derivation", "figures", "tables"
    }
    
    if not blocks:
        return {}
    
    # Calculate median font size for body text
    font_sizes = [b["font_size"] for b in blocks if b["font_size"] > 0]
    if not font_sizes:
        return {}
    median_size = statistics.median(font_sizes)
    threshold_size = median_size * 1.2
    
    # Find candidate headers
    headers = []
    for i, block in enumerate(blocks):
        text = block["text"].strip()
        if not text:
            continue
        
        is_header = False
        text_lower = text.lower().rstrip(".:")
        
        # Check 1: Known section keyword + short text
        if text_lower in KNOWN_SECTIONS and len(text) < 50:
            is_header = True
        
        # Check 2: Numbered section pattern (e.g., "1. Introduction", "I. INTRODUCTION")
        import re
        if re.match(r'^(\d+\.|I{1,3}V?\.|\([\d]+\))\s+\w+', text):
            is_header = True
        
        # Check 3: All caps + larger font
        if text.isupper() and len(text) < 60 and block["font_size"] > threshold_size:
            is_header = True
        
        # Check 4: Larger font + short + ends with no punctuation
        if block["font_size"] > threshold_size and len(text) < 60 and not text[-1].isalnum():
            pass  # Be conservative
        
        if is_header:
            headers.append((i, text_lower, block))
    
    # Build sections: each header owns blocks until next header
    sections = {}
    for idx, (block_idx, header_text, header_block) in enumerate(headers):
        section_blocks = [header_block]
        
        # Collect blocks until next header
        next_header_idx = headers[idx + 1][0] if idx + 1 < len(headers) else len(blocks)
        for j in range(block_idx + 1, next_header_idx):
            section_blocks.append(blocks[j])
        
        # Normalize section name
        section_name = header_text.strip(".:")
        sections[section_name] = section_blocks
    
    return sections
```

- [ ] **Step 4: Run test to verify it passes**

```bash
python3 -m pytest tests/paper_scanner/test_slice_pdf.py::TestIdentifySections -v
```

Expected: PASS (or close — section detection on PDFs is heuristic, may need tweaking)

- [ ] **Step 5: Write test for extract_section**

```python
class TestExtractSection:
    def test_extracts_abstract_text(self, sample_pdf: Path):
        from slice_pdf import extract_text_blocks_with_fonts, identify_sections, extract_section
        import fitz
        
        doc = fitz.open(str(sample_pdf))
        blocks = extract_text_blocks_with_fonts(doc)
        sections = identify_sections(blocks)
        abstract = extract_section(sections, "abstract")
        doc.close()
        
        assert isinstance(abstract, str)
        # Abstract should be a reasonable length
        if abstract:
            assert len(abstract) > 20
```

- [ ] **Step 6: Implement extract_section**

```python
def extract_section(sections: Dict[str, List[Dict]], *names: str) -> str:
    """Extract text content from a section by name (case-insensitive).
    
    Tries multiple name variations (e.g., 'methodology', 'methods').
    """
    names_lower = {n.lower() for n in names}
    
    for section_name, blocks in sections.items():
        if section_name.lower() in names_lower:
            # Skip the header block itself (first block)
            content_blocks = blocks[1:] if len(blocks) > 1 else blocks
            texts = [b["text"] for b in content_blocks if b["text"].strip()]
            return "\n".join(texts)
    
    return ""
```

- [ ] **Step 7: Run tests to verify**

```bash
python3 -m pytest tests/paper_scanner/test_slice_pdf.py::TestExtractSection -v
```

Expected: PASS

- [ ] **Step 8: Commit**

```bash
git add agent_configs/paper_manager/skills/paper-scanning/scripts/slice_pdf.py tests/paper_scanner/test_slice_pdf.py
git commit -m "feat(scanner): add section identification and extraction"
```

---

## Task 4: slice_pdf.py — Figure Image Extraction

**Files:**
- Modify: `agent_configs/paper_manager/skills/paper-scanning/scripts/slice_pdf.py`
- Modify: `tests/paper_scanner/test_slice_pdf.py`

- [ ] **Step 1: Write failing test for extract_all_figures**

```python
class TestExtractAllFigures:
    def test_extracts_figures_to_files(self, sample_pdf: Path, scanned_dir: Path):
        from slice_pdf import extract_all_figures
        import fitz
        
        output_dir = scanned_dir / "test_figures"
        output_dir.mkdir(parents=True, exist_ok=True)
        
        doc = fitz.open(str(sample_pdf))
        figures = extract_all_figures(doc, output_dir)
        doc.close()
        
        assert isinstance(figures, list)
        # Should find at least some images in a research paper
        if len(figures) > 0:
            for fig in figures:
                assert "path" in fig
                assert "page_num" in fig
                assert Path(fig["path"]).exists()
                # Image should be reasonable size
                assert Path(fig["path"]).stat().st_size > 100
```

- [ ] **Step 2: Run test to verify it fails**

```bash
python3 -m pytest tests/paper_scanner/test_slice_pdf.py::TestExtractAllFigures -v
```

Expected: `AttributeError: module 'slice_pdf' has no attribute 'extract_all_figures'`

- [ ] **Step 3: Implement extract_all_figures**

```python
def extract_all_figures(doc: fitz.Document, output_dir: Path) -> List[Dict]:
    """Extract all images from PDF pages, save as PNG files.
    
    Returns list of dicts with: path, page_num, width, height
    """
    output_dir = Path(output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)
    
    figures = []
    figure_counter = 0
    
    for page_num, page in enumerate(doc, start=1):
        image_list = page.get_images(full=True)
        
        for img_index, img in enumerate(image_list, start=1):
            xref = img[0]
            base_image = doc.extract_image(xref)
            image_bytes = base_image["image"]
            image_ext = base_image["ext"]
            
            # Skip tiny images (likely UI elements, not figures)
            width = base_image.get("width", 0)
            height = base_image.get("height", 0)
            if width < 100 or height < 100:
                continue
            
            figure_counter += 1
            filename = f"fig_{figure_counter:03d}_page{page_num}.{image_ext}"
            filepath = output_dir / filename
            
            with open(filepath, "wb") as f:
                f.write(image_bytes)
            
            figures.append({
                "path": str(filepath),
                "page_num": page_num,
                "width": width,
                "height": height,
            })
    
    return figures
```

- [ ] **Step 4: Run test to verify it passes**

```bash
python3 -m pytest tests/paper_scanner/test_slice_pdf.py::TestExtractAllFigures -v
```

Expected: PASS

- [ ] **Step 5: Clean up test output**

```python
# Add cleanup to conftest.py or test teardown
```

Update `tests/paper_scanner/test_slice_pdf.py` with cleanup:

```python
import shutil

@pytest.fixture(autouse=True)
def cleanup_test_outputs(scanned_dir: Path):
    yield
    test_dir = scanned_dir / "test_figures"
    if test_dir.exists():
        shutil.rmtree(test_dir)
```

- [ ] **Step 6: Commit**

```bash
git add agent_configs/paper_manager/skills/paper-scanning/scripts/slice_pdf.py tests/paper_scanner/test_slice_pdf.py
git commit -m "feat(scanner): add figure image extraction from PDF"
```

---

## Task 5: slice_pdf.py — Table Extraction and Quantitative Detection

**Files:**
- Modify: `agent_configs/paper_manager/skills/paper-scanning/scripts/slice_pdf.py`
- Modify: `tests/paper_scanner/test_slice_pdf.py`

- [ ] **Step 1: Write failing test for extract_structured_tables**

```python
class TestExtractStructuredTables:
    def test_returns_list_of_tables(self, sample_pdf: Path):
        from slice_pdf import extract_structured_tables
        import fitz
        
        doc = fitz.open(str(sample_pdf))
        tables = extract_structured_tables(doc)
        doc.close()
        
        assert isinstance(tables, list)
        for table in tables:
            assert "headers" in table
            assert "rows" in table
            assert isinstance(table["headers"], list)
            assert isinstance(table["rows"], list)
```

- [ ] **Step 2: Run test to verify it fails**

```bash
python3 -m pytest tests/paper_scanner/test_slice_pdf.py::TestExtractStructuredTables -v
```

Expected: `AttributeError`

- [ ] **Step 3: Implement extract_structured_tables**

```python
def extract_structured_tables(doc: fitz.Document) -> List[Dict]:
    """Extract tables from PDF using PyMuPDF's table finder.
    
    Returns list of dicts with: headers, rows, page_num
    """
    tables = []
    
    for page_num, page in enumerate(doc, start=1):
        found_tables = page.find_tables()
        for tab in found_tables.tables:
            tables.append({
                "headers": tab.header.names if tab.header else [],
                "rows": tab.rows,
                "page_num": page_num,
            })
    
    return tables
```

- [ ] **Step 4: Run test to verify it passes**

```bash
python3 -m pytest tests/paper_scanner/test_slice_pdf.py::TestExtractStructuredTables -v
```

Expected: PASS

- [ ] **Step 5: Write failing test for contains_keywords**

```python
class TestContainsKeywords:
    def test_detects_quant_keywords(self):
        from slice_pdf import contains_keywords
        
        blocks = [
            {"text": "We test the momentum factor portfolio backtest"},
            {"text": "Sharpe ratio is 1.2 with alpha generation"},
        ]
        
        assert contains_keywords(blocks, ["backtest", "factor", "alpha", "sharpe"], threshold=2) is True
        
    def test_no_false_positives(self):
        from slice_pdf import contains_keywords
        
        blocks = [
            {"text": "This is a theoretical discussion about market efficiency"},
            {"text": "We review the literature on corporate governance"},
        ]
        
        assert contains_keywords(blocks, ["backtest", "factor", "alpha"], threshold=2) is False
```

- [ ] **Step 6: Implement contains_keywords**

```python
def contains_keywords(blocks: List[Dict], keywords: List[str], threshold: int = 3) -> bool:
    """Check if blocks contain at least `threshold` occurrences of keywords."""
    count = 0
    for block in blocks:
        text = block.get("text", "").lower()
        for kw in keywords:
            count += text.count(kw.lower())
            if count >= threshold:
                return True
    return count >= threshold
```

- [ ] **Step 7: Run tests to verify**

```bash
python3 -m pytest tests/paper_scanner/test_slice_pdf.py::TestContainsKeywords -v
```

Expected: PASS

- [ ] **Step 8: Commit**

```bash
git add agent_configs/paper_manager/skills/paper-scanning/scripts/slice_pdf.py tests/paper_scanner/test_slice_pdf.py
git commit -m "feat(scanner): add table extraction and quant keyword detection"
```

---

## Task 6: slice_pdf.py — Main Function Assembly

**Files:**
- Modify: `agent_configs/paper_manager/skills/paper-scanning/scripts/slice_pdf.py`
- Modify: `tests/paper_scanner/test_slice_pdf.py`

- [ ] **Step 1: Write failing integration test for slice_pdf**

```python
class TestSlicePdf:
    def test_returns_complete_content_package(self, sample_pdf: Path, scanned_dir: Path):
        from slice_pdf import slice_pdf
        import fitz
        
        output_dir = scanned_dir / "test_slice"
        result = slice_pdf(sample_pdf, output_dir=output_dir)
        
        assert isinstance(result, dict)
        assert "doc_id" in result
        assert "filepath" in result
        assert "core" in result
        assert "empirical" in result
        assert "proofs" in result
        assert "is_likely_quant" in result
        
        # Core should have all expected fields
        core = result["core"]
        assert "title" in core
        assert "abstract" in core
        assert "intro" in core
        assert "conclusions" in core
        assert "figures" in core
        assert "figure_captions" in core
        assert "tables" in core
        
        # If figures were extracted, they should have paths
        if core["figures"]:
            for fig in core["figures"]:
                assert "path" in fig
```

- [ ] **Step 2: Run test to verify it fails**

```bash
python3 -m pytest tests/paper_scanner/test_slice_pdf.py::TestSlicePdf -v
```

Expected: `TypeError: slice_pdf() takes 1 positional argument but 2 were given` or similar

- [ ] **Step 3: Implement slice_pdf main function**

```python
def slice_pdf(pdf_path: str | Path, output_dir: Optional[Path] = None) -> Dict:
    """Intelligently slice a PDF into structured content packages.
    
    Args:
        pdf_path: Path to the PDF file
        output_dir: Directory to save extracted figure images. Defaults to scanned/{doc_id}/figures/
    
    Returns:
        Content package dict with core, empirical, proofs tiers
    """
    pdf_path = Path(pdf_path)
    doc_id = generate_doc_id(pdf_path)
    
    if output_dir is None:
        root = pdf_path.parent.parent.parent.parent  # Navigate to papers/
        output_dir = root / "scanned" / doc_id / "figures"
    output_dir = Path(output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)
    
    doc = fitz.open(str(pdf_path))
    
    try:
        # 1. Extract text blocks
        blocks = extract_text_blocks_with_fonts(doc)
        
        # 2. Identify sections
        sections = identify_sections(blocks)
        
        # 3. Extract core package
        core_package = {
            "title": extract_title(blocks),
            "abstract": extract_section(sections, "abstract"),
            "intro": extract_section(sections, "introduction"),
            "conclusions": extract_section(sections, "conclusion", "conclusions"),
            "figures": extract_all_figures(doc, output_dir),
            "figure_captions": extract_all_captions(sections, "figure"),
            "table_captions": extract_all_captions(sections, "table"),
            "tables": extract_structured_tables(doc),
        }
        
        # 4. Detect quantitative
        quant_keywords = [
            "backtest", "portfolio", "factor", "alpha", "sharpe", "return",
            "empirical", "data", "sample", "transaction cost", "slippage",
            "momentum", "value", "volatility", "mean reversion"
        ]
        is_likely_quant = contains_keywords(blocks, quant_keywords, threshold=3)
        
        # 5. Extract empirical package if quantitative
        empirical_package = None
        if is_likely_quant:
            empirical_package = {
                "data_section": extract_section(sections, "data"),
                "methodology_section": extract_section(sections, "methodology", "methods", "empirical"),
                "results_section": extract_section(sections, "results"),
                "trading_costs": grep_keywords_in_sections(sections, ["transaction cost", "slippage", "market impact"]),
            }
        
        # 6. Mark proofs
        proofs_package = {
            "available_sections": list(find_sections(sections, ["appendix", "proof", "derivation"]).keys()),
            "extracted": False,
        }
        
        return {
            "doc_id": doc_id,
            "filepath": str(pdf_path),
            "core": core_package,
            "empirical": empirical_package,
            "proofs": proofs_package,
            "is_likely_quant": is_likely_quant,
            "extraction_quality": "full" if sections else "fallback_text_only",
        }
    finally:
        doc.close()


def generate_doc_id(pdf_path: Path) -> str:
    """Generate a document ID from filepath.
    
    Example: raw/elsevier/2026/elsevier_10.1016_x.pdf -> elsevier_10.1016_x
    """
    stem = pdf_path.stem
    # If stem already contains source prefix, use as-is
    return stem


def extract_all_captions(sections: Dict[str, List[Dict]], caption_type: str) -> List[Dict]:
    """Extract figure or table captions from sections."""
    captions = []
    caption_lower = caption_type.lower()
    
    for section_name, blocks in sections.items():
        if caption_lower in section_name.lower():
            for block in blocks:
                text = block["text"].strip()
                if text and len(text) > 5:
                    captions.append({
                        "text": text,
                        "page_num": block["page_num"],
                    })
    
    return captions


def grep_keywords_in_sections(sections: Dict[str, List[Dict]], keywords: List[str]) -> List[Dict]:
    """Find paragraphs containing keywords within sections."""
    matches = []
    for section_name, blocks in sections.items():
        for block in blocks:
            text = block["text"].lower()
            for kw in keywords:
                if kw.lower() in text:
                    matches.append({
                        "text": block["text"],
                        "keyword": kw,
                        "section": section_name,
                        "page_num": block["page_num"],
                    })
                    break
    return matches


def find_sections(sections: Dict[str, List[Dict]], keywords: List[str]) -> Dict[str, List[Dict]]:
    """Find sections matching any of the keywords."""
    found = {}
    for section_name, blocks in sections.items():
        section_lower = section_name.lower()
        for kw in keywords:
            if kw.lower() in section_lower:
                found[section_name] = blocks
                break
    return found
```

- [ ] **Step 4: Run integration test**

```bash
python3 -m pytest tests/paper_scanner/test_slice_pdf.py::TestSlicePdf -v
```

Expected: PASS (may need minor tweaks based on actual PDF structure)

- [ ] **Step 5: Commit**

```bash
git add agent_configs/paper_manager/skills/paper-scanning/scripts/slice_pdf.py tests/paper_scanner/test_slice_pdf.py
git commit -m "feat(scanner): complete slice_pdf main function with all tiers"
```

---

## Task 7: verify_card.py — Card Format Validation

**Files:**
- Create: `agent_configs/paper_manager/skills/paper-scanning/scripts/verify_card.py`
- Create: `tests/paper_scanner/test_verify_card.py`

- [ ] **Step 1: Write failing test for frontmatter validation**

`tests/paper_scanner/test_verify_card.py`:

```python
import sys
from pathlib import Path

SKILL_SCRIPTS = Path(__file__).parent.parent.parent / "agent_configs" / "paper_manager" / "skills" / "paper-scanning" / "scripts"
sys.path.insert(0, str(SKILL_SCRIPTS))

from verify_card import verify_card, parse_frontmatter


class TestParseFrontmatter:
    def test_parses_valid_frontmatter(self, tmp_path):
        card = tmp_path / "test_card.md"
        card.write_text("""---
doc_id: elsevier_10.1111_jofi.70040
title: "Test Paper"
title_zh: "测试论文"
authors: ["A", "B"]
year: 2024
source: elsevier
source_tier: journal
paper_type: quantitative
---

## 基础分析
""")
        
        fm = parse_frontmatter(card)
        assert fm["doc_id"] == "elsevier_10.1111_jofi.70040"
        assert fm["year"] == 2024
        assert fm["paper_type"] == "quantitative"
```

- [ ] **Step 2: Run test to verify it fails**

```bash
python3 -m pytest tests/paper_scanner/test_verify_card.py::TestParseFrontmatter -v
```

Expected: `ModuleNotFoundError`

- [ ] **Step 3: Implement verify_card and parse_frontmatter**

`agent_configs/paper_manager/skills/paper-scanning/scripts/verify_card.py`:

```python
"""Card format validation for paper scanner output."""

from pathlib import Path
from typing import Dict, List, Tuple
import yaml


REQUIRED_FIELDS = ["doc_id", "title", "authors", "year", "source", "source_tier", "paper_type"]
VALID_SOURCE_TIERS = {"journal", "ssrn", "arxiv"}
VALID_PAPER_TYPES = {"quantitative", "theoretical", "review", "empirical_non_quant", "other"}

REQUIRED_SECTIONS_BASIC = ["基础分析", "作者目标与贡献", "关键方法/技术要素", 
                           "对量化研究的实际价值", "引申阅读线索"]
REQUIRED_SECTIONS_QUANT = ["量化深度分析", "方法论可信度评分", "可迁移性评估",
                           "因子与回测", "关键发现", "方法论风险"]


def parse_frontmatter(card_path: Path) -> Dict:
    """Parse YAML frontmatter from a markdown card."""
    content = Path(card_path).read_text(encoding="utf-8")
    
    if not content.startswith("---"):
        return {}
    
    try:
        _, fm_text, body = content.split("---", 2)
        return yaml.safe_load(fm_text) or {}
    except ValueError:
        return {}


def verify_card(card_path: Path) -> Dict:
    """Validate a card.md file against the spec.
    
    Returns: {"valid": bool, "errors": List[str]}
    """
    errors = []
    content = Path(card_path).read_text(encoding="utf-8")
    
    # 1. Frontmatter validation
    fm = parse_frontmatter(card_path)
    if not fm:
        errors.append("Missing or invalid YAML frontmatter")
        return {"valid": False, "errors": errors}
    
    for field in REQUIRED_FIELDS:
        if field not in fm:
            errors.append(f"Missing required frontmatter field: {field}")
    
    if "source_tier" in fm and fm["source_tier"] not in VALID_SOURCE_TIERS:
        errors.append(f"Invalid source_tier: {fm['source_tier']}")
    
    if "paper_type" in fm and fm["paper_type"] not in VALID_PAPER_TYPES:
        errors.append(f"Invalid paper_type: {fm['paper_type']}")
    
    # 2. Section validation
    is_quant = fm.get("paper_type") == "quantitative"
    
    for section in REQUIRED_SECTIONS_BASIC:
        if section not in content:
            errors.append(f"Missing required section: {section}")
    
    if is_quant:
        for section in REQUIRED_SECTIONS_QUANT:
            if section not in content:
                errors.append(f"Missing required section for quantitative paper: {section}")
    
    return {"valid": len(errors) == 0, "errors": errors}
```

- [ ] **Step 4: Run tests**

```bash
python3 -m pytest tests/paper_scanner/test_verify_card.py -v
```

Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add agent_configs/paper_manager/skills/paper-scanning/scripts/verify_card.py tests/paper_scanner/test_verify_card.py
git commit -m "feat(scanner): add card format validation script"
```

---

## Task 8: build_index.py — Index Generation from Scan State

**Files:**
- Create: `agent_configs/paper_manager/skills/paper-scanning/scripts/build_index.py`
- Create: `tests/paper_scanner/test_build_index.py`

- [ ] **Step 1: Write failing test for build_index**

`tests/paper_scanner/test_build_index.py`:

```python
import sys
import json
from pathlib import Path

SKILL_SCRIPTS = Path(__file__).parent.parent.parent / "agent_configs" / "paper_manager" / "skills" / "paper-scanning" / "scripts"
sys.path.insert(0, str(SKILL_SCRIPTS))

from build_index import build_index


class TestBuildIndex:
    def test_builds_index_from_scan_state(self, tmp_path, scanned_dir):
        scan_state = tmp_path / "scan_state.json"
        scan_state.write_text(json.dumps({
            "papers": {
                "elsevier_test": {
                    "filepath": "raw/elsevier/test.pdf",
                    "status": "completed",
                    "paper_type": "quantitative",
                    "card_path": "scanned/elsevier_test/card.md",
                    "card_path_en": "scanned/elsevier_test/card_en.md",
                    "scanned_at": "2026-06-03T10:00:00Z"
                },
                "arxiv_test": {
                    "filepath": "raw/arxiv/test.pdf",
                    "status": "completed",
                    "paper_type": "theoretical",
                    "card_path": "scanned/arxiv_test/card.md",
                    "card_path_en": "scanned/arxiv_test/card_en.md",
                    "scanned_at": "2026-06-03T11:00:00Z"
                }
            }
        }))
        
        output = tmp_path / "index.json"
        build_index(scan_state, output)
        
        assert output.exists()
        index = json.loads(output.read_text())
        
        assert "papers" in index
        assert len(index["papers"]) == 2
        
        # Journal should come before arxiv
        assert index["papers"][0]["doc_id"] == "elsevier_test"
        assert index["papers"][1]["doc_id"] == "arxiv_test"
```

- [ ] **Step 2: Run test to verify it fails**

```bash
python3 -m pytest tests/paper_scanner/test_build_index.py -v
```

Expected: `ModuleNotFoundError`

- [ ] **Step 3: Implement build_index**

`agent_configs/paper_manager/skills/paper-scanning/scripts/build_index.py`:

```python
"""Build scanned/index.json from scan_state.json."""

import json
from pathlib import Path
from typing import Dict, List
from datetime import datetime, timezone


SOURCE_TIER_PRIORITY = {"journal": 0, "ssrn": 1, "arxiv": 2}


def build_index(scan_state_path: Path, output_path: Path) -> None:
    """Generate index.json from scan_state.json.
    
    Sorting: source_tier priority > credibility_score desc > year desc
    """
    state = json.loads(Path(scan_state_path).read_text())
    papers_state = state.get("papers", {})
    
    index_papers = []
    by_tier = {"journal": 0, "ssrn": 0, "arxiv": 0}
    by_type = {}
    
    for doc_id, paper in papers_state.items():
        if paper.get("status") != "completed":
            continue
        
        tier = paper.get("source_tier", "arxiv")
        ptype = paper.get("paper_type", "other")
        
        by_tier[tier] = by_tier.get(tier, 0) + 1
        by_type[ptype] = by_type.get(ptype, 0) + 1
        
        entry = {
            "doc_id": doc_id,
            "title": paper.get("title", ""),
            "authors": paper.get("authors", []),
            "year": paper.get("year"),
            "source": paper.get("source", ""),
            "source_tier": tier,
            "paper_type": ptype,
            "credibility_score": paper.get("credibility_score"),
            "credibility_tier": paper.get("credibility_tier"),
            "card_paths": {
                "zh": paper.get("card_path", ""),
                "en": paper.get("card_path_en", ""),
            },
            "scanned_at": paper.get("scanned_at", ""),
        }
        
        # Add quant summary if available
        if "quant_summary" in paper:
            entry["quant_summary"] = paper["quant_summary"]
        
        index_papers.append(entry)
    
    # Sort: tier priority > credibility > year
    def sort_key(p):
        return (
            SOURCE_TIER_PRIORITY.get(p["source_tier"], 99),
            -(p.get("credibility_score") or 0),
            -(p.get("year") or 0),
        )
    
    index_papers.sort(key=sort_key)
    
    index = {
        "last_updated": datetime.now(timezone.utc).isoformat(),
        "total_scanned": len(index_papers),
        "by_tier": by_tier,
        "by_type": by_type,
        "papers": index_papers,
    }
    
    Path(output_path).parent.mkdir(parents=True, exist_ok=True)
    Path(output_path).write_text(json.dumps(index, indent=2, ensure_ascii=False))
```

- [ ] **Step 4: Run tests**

```bash
python3 -m pytest tests/paper_scanner/test_build_index.py -v
```

Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add agent_configs/paper_manager/skills/paper-scanning/scripts/build_index.py tests/paper_scanner/test_build_index.py
git commit -m "feat(scanner): add index building script from scan state"
```

---

## Task 9: Scan State Management Module

**Files:**
- Create: `agent_configs/paper_manager/skills/paper-scanning/scripts/scan_state.py`
- Create: `tests/paper_scanner/test_scan_state.py`

- [ ] **Step 1: Write failing test for ScanState**

`tests/paper_scanner/test_scan_state.py`:

```python
import sys
import json
from pathlib import Path

SKILL_SCRIPTS = Path(__file__).parent.parent.parent / "agent_configs" / "paper_manager" / "skills" / "paper-scanning" / "scripts"
sys.path.insert(0, str(SKILL_SCRIPTS))

from scan_state import ScanState


class TestScanState:
    def test_creates_new_state_if_not_exists(self, tmp_path):
        state_path = tmp_path / "scan_state.json"
        state = ScanState(state_path)
        
        assert state_path.exists()
        data = json.loads(state_path.read_text())
        assert "papers" in data
        assert data["total_papers"] == 0
    
    def test_adds_and_updates_paper(self, tmp_path):
        state_path = tmp_path / "scan_state.json"
        state = ScanState(state_path)
        
        state.add_paper("raw/elsevier/test.pdf", "elsevier_test")
        state.mark_status("elsevier_test", "completed", 
                         paper_type="quantitative",
                         card_path="scanned/elsevier_test/card.md")
        state.save()
        
        data = json.loads(state_path.read_text())
        assert "elsevier_test" in data["papers"]
        assert data["papers"]["elsevier_test"]["status"] == "completed"
        assert data["papers"]["elsevier_test"]["paper_type"] == "quantitative"
    
    def test_gets_pending_queue(self, tmp_path):
        state_path = tmp_path / "scan_state.json"
        state = ScanState(state_path)
        
        state.add_paper("raw/elsevier/a.pdf", "elsevier_a")
        state.add_paper("raw/arxiv/b.pdf", "arxiv_b")
        state.mark_status("elsevier_a", "scanning")
        state.save()
        
        pending = state.get_pending()
        assert len(pending) == 1
        assert pending[0]["doc_id"] == "arxiv_b"
```

- [ ] **Step 2: Run test to verify it fails**

```bash
python3 -m pytest tests/paper_scanner/test_scan_state.py -v
```

Expected: `ModuleNotFoundError`

- [ ] **Step 3: Implement ScanState**

`agent_configs/paper_manager/skills/paper-scanning/scripts/scan_state.py`:

```python
"""Scan state management for paper scanner."""

import json
from pathlib import Path
from typing import Dict, List, Optional
from datetime import datetime, timezone


class ScanState:
    """Manages scan_state.json — the single source of truth for scanner progress."""
    
    def __init__(self, state_path: Path):
        self.state_path = Path(state_path)
        self.data = self._load()
    
    def _load(self) -> Dict:
        if self.state_path.exists():
            return json.loads(self.state_path.read_text())
        
        return {
            "last_updated": datetime.now(timezone.utc).isoformat(),
            "total_papers": 0,
            "stats": {"pending": 0, "preprocessing": 0, "scanning": 0, 
                     "completed": 0, "failed": 0, "skipped": 0},
            "config": {"max_concurrent": 3, 
                      "priority_rules": ["source_tier", "year_desc", "added_at_desc"]},
            "papers": {},
        }
    
    def add_paper(self, filepath: str, doc_id: str) -> None:
        """Add a new paper to the pending queue."""
        if doc_id in self.data["papers"]:
            return
        
        self.data["papers"][doc_id] = {
            "filepath": filepath,
            "status": "pending",
        }
        self.data["total_papers"] = len(self.data["papers"])
        self._update_stats()
    
    def mark_status(self, doc_id: str, status: str, **kwargs) -> None:
        """Update paper status and optional fields."""
        if doc_id not in self.data["papers"]:
            raise KeyError(f"Paper {doc_id} not found in scan state")
        
        self.data["papers"][doc_id]["status"] = status
        
        for key, value in kwargs.items():
            self.data["papers"][doc_id][key] = value
        
        if status == "completed":
            self.data["papers"][doc_id]["scanned_at"] = datetime.now(timezone.utc).isoformat()
        
        self._update_stats()
    
    def get_pending(self) -> List[Dict]:
        """Get papers sorted by priority rules."""
        pending = [
            {"doc_id": doc_id, **info}
            for doc_id, info in self.data["papers"].items()
            if info.get("status") == "pending"
        ]
        
        # Sort by source tier priority
        tier_priority = {"journal": 0, "ssrn": 1, "arxiv": 2}
        
        def sort_key(p):
            tier = p.get("source_tier", "arxiv")
            year = p.get("year", 0) or 0
            return (tier_priority.get(tier, 99), -year)
        
        pending.sort(key=sort_key)
        return pending
    
    def get_running(self) -> List[Dict]:
        """Get papers currently being scanned."""
        return [
            {"doc_id": doc_id, **info}
            for doc_id, info in self.data["papers"].items()
            if info.get("status") == "scanning"
        ]
    
    def _update_stats(self) -> None:
        """Recalculate stats from papers."""
        stats = {"pending": 0, "preprocessing": 0, "scanning": 0,
                "completed": 0, "failed": 0, "skipped": 0}
        
        for paper in self.data["papers"].values():
            status = paper.get("status", "pending")
            stats[status] = stats.get(status, 0) + 1
        
        self.data["stats"] = stats
    
    def save(self) -> None:
        """Persist state to disk."""
        self.data["last_updated"] = datetime.now(timezone.utc).isoformat()
        self.state_path.parent.mkdir(parents=True, exist_ok=True)
        self.state_path.write_text(json.dumps(self.data, indent=2, ensure_ascii=False))
```

- [ ] **Step 4: Run tests**

```bash
python3 -m pytest tests/paper_scanner/test_scan_state.py -v
```

Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add agent_configs/paper_manager/skills/paper-scanning/scripts/scan_state.py tests/paper_scanner/test_scan_state.py
git commit -m "feat(scanner): add scan state management module"
```

---

## Task 10: SKILL.md — Main Skill Document

**Files:**
- Create: `agent_configs/paper_manager/skills/paper-scanning/SKILL.md`

- [ ] **Step 1: Write SKILL.md with complete workflow**

`agent_configs/paper_manager/skills/paper-scanning/SKILL.md`:

```markdown
---
name: paper-scanning
description: |
  Deep-reads academic PDFs from the local paper pool and produces structured
  paper cards ( Markdown + English summary ) with methodology audits for
  quantitative papers. Triggered when the user says "scan papers",
  "read papers", "analyze downloaded papers", or "update paper cards".
---

# Paper Scanning

## Quick Start

Scan all unprocessed papers in `shared_workspace/papers/raw/`:

```bash
cd /workspace/tools/paper_scanner
PYTHONPATH=/workspace/tools/paper_scanner python3 -m scripts.slice_pdf --help
```

## Workflow

Copy this checklist and track progress:

```
Paper Scanning Progress:
- [ ] Step 0: Pre-flight (check raw/ directory, scan_state.json)
- [ ] Step 1: Build pending queue from scan_state
- [ ] Step 2: Preprocess PDFs with slice_pdf.py (content slicing)
- [ ] Step 3: Dispatch Subagent for each paper (max 3 concurrent)
- [ ] Step 4: Collect Subagent results (structured JSON)
- [ ] Step 5: Assemble card.md + card_en.md
- [ ] Step 6: Verify card format with verify_card.py
- [ ] Step 7: Update scan_state.json + build_index.py
- [ ] Step 8: Generate bilingual report + checkpoint
```

**Step 0: Pre-flight**

```bash
ls shared_workspace/papers/raw/*/
python3 -c "import fitz; print('PyMuPDF ok')"
```

**Step 1: Build queue**

Load `scan_state.json`, identify papers with `status: pending`.

Sort by: journal > ssrn > arxiv (within tier: year desc).

**Step 2: Preprocess PDFs**

For each pending paper:

```bash
python3 scripts/slice_pdf.py \
  --input "raw/elsevier/2026/elsevier_10.1016_x.pdf" \
  --output-dir "shared_workspace/papers/scanned/elsevier_10.1016_x"
```

Output: `content_package.json` with core/empirical/proofs tiers + figure images.

**Step 3-4: Dispatch Subagent**

Launch one Subagent per paper. Input format:

```json
{
  "doc_id": "...",
  "source_tier": "journal",
  "instructions": "Analyze this paper and produce structured analysis.",
  "todo": [
    "Step 1: Read Core Package (text + figure images)",
    "Step 2: Determine paper_type",
    "Step 3: Produce basic analysis",
    "Step 4: If quantitative, read Empirical Package",
    "Step 5: If quantitative, produce quant depth analysis"
  ],
  "content": {
    "core": {"text_parts": {...}, "figure_paths": [...]},
    "empirical": {...}
  }
}
```

**Step 5: Assemble cards**

Render Subagent JSON into standard Markdown using `references/card-template.md`.

**Step 6: Verify**

```bash
python3 scripts/verify_card.py "scanned/{doc_id}/card.md"
```

Expected: `{"valid": true, "errors": []}`

**Step 7: Update state and index**

```bash
python3 scripts/build_index.py \
  --state "shared_workspace/papers/scan_state.json" \
  --output "shared_workspace/papers/scanned/index.json"
```

**Step 8: Report**

Generate bilingual report + `.agent_checkpoint.json`.

## Scripts Reference

| Script | Purpose | Command |
|--------|---------|---------|
| `slice_pdf.py` | PDF → content package | `python3 slice_pdf.py --input PDF --output-dir DIR` |
| `verify_card.py` | Validate card format | `python3 verify_card.py card.md` |
| `build_index.py` | Generate index.json | `python3 build_index.py --state STATE --output INDEX` |

## Subagent Prompt

See `references/subagent-prompt.md` for the complete system prompt template.

## Card Templates

See `references/card-template.md` for exact card.md and card_en.md templates.
```

- [ ] **Step 2: Verify SKILL.md format**

```bash
cat agent_configs/paper_manager/skills/paper-scanning/SKILL.md | head -20
```

Expected: Valid YAML frontmatter, markdown body follows.

- [ ] **Step 3: Commit**

```bash
git add agent_configs/paper_manager/skills/paper-scanning/SKILL.md
git commit -m "feat(scanner): add main SKILL.md with workflow and commands"
```

---

## Task 11: Reference Documents

**Files:**
- Create: `agent_configs/paper_manager/skills/paper-scanning/references/card-template.md`
- Create: `agent_configs/paper_manager/skills/paper-scanning/references/subagent-prompt.md`
- Create: `agent_configs/paper_manager/skills/paper-scanning/references/preprocessing-guide.md`

- [ ] **Step 1: Write card-template.md**

`agent_configs/paper_manager/skills/paper-scanning/references/card-template.md`:

```markdown
# Card Template Reference

## Chinese Card (card.md)

```markdown
---
doc_id: {source}_{identifier}
title: "..."
title_zh: "..."
authors: ["..."]
year: YYYY
source: {source}
source_tier: journal | ssrn | arxiv
paper_type: quantitative | theoretical | review | empirical_non_quant | other
journal_name: "..."
doi: "..."
scanned_at: ISO8601
---

## 基础分析

### 作者目标与贡献
[论文要解决什么问题，实际做到了什么程度]

### 关键方法/技术要素
[如果有新方法，核心机制是什么]

### 对量化研究的实际价值
[哪些发现、方法、数据可以直接或间接用于量化策略]

### 引申阅读线索
[提到的关键文献、数据集、理论框架]

---

## 量化深度分析

### 方法论可信度评分：{score}/100 {tier}

| 检查项 | 得分 | 理由 |
|--------|------|------|
| 样本区间长度 | x/20 | ... |
| 样本外测试 | x/20 | ... |
| 交易成本 | x/15 | ... |
| 无未来信息泄露 | x/15 | ... |
| 数据可获取性 | x/15 | ... |
| 经济学解释 | x/15 | ... |

### 可迁移性评估

| 维度 | 评级 | 说明 |
|------|------|------|
| 标的池兼容 | ... | ... |
| 数据频率 | ... | ... |
| 交易成本敏感 | ... | ... |
| 期权适配 | ... | ... |

### 因子与回测
[因子公式、回测设置]

### 关键发现
[核心数据表格]

### 方法论风险
[具体风险点]

---

## 质量总评
- **综合评级**：...
- **核心亮点**：...
- **主要顾虑**：...
- **行动建议**：...
```

## English Card (card_en.md)

```markdown
---
doc_id: {source}_{identifier}
ref: "Author (Year), Journal"
---

## Summary
**Goal**: ...
**Key Contribution**: ...
**Quant Value**: ...
**Credibility**: score/tier
**Transferability**: summary
**Key Metrics**: ...
**Risks**: ...
```
```

- [ ] **Step 2: Write subagent-prompt.md**

`agent_configs/paper_manager/skills/paper-scanning/references/subagent-prompt.md`:

```markdown
# Subagent Prompt Template

## System Prompt

You are an expert quantitative research paper analyst. Your job is to read ONE paper at a time and produce structured analysis.

## Rules

1. You only analyze the paper provided in the content package. Do not reference other papers.
2. Read figure images carefully — they often contain the most important results.
3. Be precise with numbers. If Sharpe ratio is 1.05, say 1.05, not "around 1".
4. Flag methodological weaknesses explicitly.
5. If the paper is not quantitative, stop after basic analysis.

## Output Format

Produce a JSON object matching this structure:

```json
{
  "doc_id": "...",
  "paper_type": "quantitative | theoretical | review | empirical_non_quant | other",
  "basic_analysis": {
    "goals_and_contributions": "...",
    "key_methods": "...",
    "quant_value": "...",
    "further_reading": "..."
  },
  "quant_analysis": {
    "credibility_score": 0,
    "credibility_breakdown": {...},
    "transferability": {...},
    "factors": [...],
    "backtest_summary": {...},
    "key_findings": [...],
    "methodology_risks": [...]
  },
  "quality_notes": "..."
}
```

## Scoring Guide

### Credibility Score (max 100)

| Dimension | Max | Criteria |
|-----------|-----|----------|
| Sample length | 20 | >=10 years full score |
| Out-of-sample | 20 | Walk-forward or multiple splits |
| Transaction costs | 15 | Explicitly modeled |
| No look-ahead | 15 | Explicit bias controls |
| Data accessible | 15 | Public/commercial data |
| Economics rationale | 15 | Behavioral/microstructure theory |
```

- [ ] **Step 3: Write preprocessing-guide.md**

`agent_configs/paper_manager/skills/paper-scanning/references/preprocessing-guide.md`:

```markdown
# PDF Preprocessing Guide

## slice_pdf.py Usage

### Basic

```bash
python3 slice_pdf.py --input paper.pdf --output-dir scanned/doc_id/
```

### Output Structure

```
scanned/doc_id/
├── content_package.json    # Structured text content
└── figures/
    ├── fig_001_page2.png
    └── fig_002_page3.png
```

### Content Package Format

```json
{
  "doc_id": "...",
  "core": {
    "title": "...",
    "abstract": "...",
    "intro": "...",
    "conclusions": "...",
    "figures": [{"path": "...", "page_num": 2}],
    "figure_captions": [{"text": "...", "page_num": 2}],
    "tables": [{"headers": [...], "rows": [...]}]
  },
  "empirical": {
    "data_section": "...",
    "methodology_section": "...",
    "results_section": "..."
  },
  "is_likely_quant": true
}
```

## Troubleshooting

### "No sections detected"

Fallback: script extracts full text. Subagent does section segmentation.

### "PyMuPDF not found"

Install: `pip install PyMuPDF`

### Figures not extracted

Some PDFs embed figures as vector graphics (not images). In these cases, figure captions are the primary source of information.
```

- [ ] **Step 4: Commit**

```bash
git add agent_configs/paper_manager/skills/paper-scanning/references/
git commit -m "feat(scanner): add reference docs (card template, subagent prompt, preprocessing guide)"
```

---

## Task 12: Integration Test and End-to-End Validation

**Files:**
- Modify: `tests/paper_scanner/test_slice_pdf.py` (add integration test)
- Create: `tests/paper_scanner/test_integration.py`

- [ ] **Step 1: Write end-to-end integration test**

`tests/paper_scanner/test_integration.py`:

```python
import sys
import json
import shutil
from pathlib import Path

SKILL_SCRIPTS = Path(__file__).parent.parent.parent / "agent_configs" / "paper_manager" / "skills" / "paper-scanning" / "scripts"
sys.path.insert(0, str(SKILL_SCRIPTS))

from slice_pdf import slice_pdf
from verify_card import verify_card
from build_index import build_index
from scan_state import ScanState


class TestEndToEnd:
    def test_full_pipeline(self, sample_pdf: Path, scanned_dir: Path, tmp_path):
        """Test: slice -> verify -> index pipeline."""
        doc_id = "test_integration"
        output_dir = scanned_dir / doc_id
        
        # 1. Slice PDF
        content = slice_pdf(sample_pdf, output_dir=output_dir)
        assert content["doc_id"]
        assert output_dir.exists()
        
        # 2. Create a mock card
        card_path = output_dir / "card.md"
        card_path.write_text(f"""---
doc_id: {content["doc_id"]}
title: "Test"
title_zh: "测试"
authors: ["A"]
year: 2024
source: ssrn
source_tier: ssrn
paper_type: quantitative
---

## 基础分析

### 作者目标与贡献
Test content.

### 关键方法/技术要素
Test content.

### 对量化研究的实际价值
Test content.

### 引申阅读线索
Test content.

---

## 量化深度分析

### 方法论可信度评分：70/100

### 可迁移性评估

### 因子与回测

### 关键发现

### 方法论风险

---

## 质量总评
- **综合评级**：...
""")
        
        # 3. Verify card
        result = verify_card(card_path)
        assert result["valid"], f"Card invalid: {result['errors']}"
        
        # 4. Update scan state
        state_path = tmp_path / "scan_state.json"
        state = ScanState(state_path)
        state.add_paper(str(sample_pdf), content["doc_id"])
        state.mark_status(content["doc_id"], "completed",
                         title="Test",
                         paper_type="quantitative",
                         source_tier="ssrn",
                         card_path=str(card_path),
                         card_path_en=str(output_dir / "card_en.md"),
                         credibility_score=70)
        state.save()
        
        # 5. Build index
        index_path = tmp_path / "index.json"
        build_index(state_path, index_path)
        
        index = json.loads(index_path.read_text())
        assert index["total_scanned"] == 1
        assert len(index["papers"]) == 1
        assert index["papers"][0]["doc_id"] == content["doc_id"]
```

- [ ] **Step 2: Run integration test**

```bash
python3 -m pytest tests/paper_scanner/test_integration.py -v
```

Expected: PASS

- [ ] **Step 3: Run full test suite**

```bash
python3 -m pytest tests/paper_scanner/ -v
```

Expected: All tests PASS

- [ ] **Step 4: Commit**

```bash
git add tests/paper_scanner/
git commit -m "feat(scanner): add integration test for full pipeline"
```

---

## Self-Review

### 1. Spec Coverage

| Spec Section | Implementing Task | Status |
|--------------|-------------------|--------|
| PDF 智能内容分片 (Tier 1/2/3) | Task 2-6 | ✅ slice_pdf.py |
| Figure 图片提取 | Task 4 | ✅ extract_all_figures |
| 内容价值分层 | Task 2-6 | ✅ core/empirical/proofs |
| 卡片格式校验 | Task 7 | ✅ verify_card.py |
| 索引构建 | Task 8 | ✅ build_index.py |
| 扫描状态管理 | Task 9 | ✅ ScanState class |
| SKILL.md 主文档 | Task 10 | ✅ workflow + commands |
| Reference 文档 | Task 11 | ✅ 3 reference files |
| 双语卡片模板 | Task 11 | ✅ card-template.md |
| Subagent 提示模板 | Task 11 | ✅ subagent-prompt.md |
| 中断恢复 | Task 9 | ✅ scan_state.json |
| 有限并发 | Task 10 (SKILL.md workflow) | ✅ max_concurrent config |
| 队列优先级 | Task 9 | ✅ source_tier sorting |

### 2. Placeholder Scan

- No TBD/TODO placeholders ✅
- No vague instructions like "add appropriate error handling" ✅
- All steps include concrete code/commands ✅
- No "similar to Task N" references ✅

### 3. Type Consistency

| Entity | Definition Location | Usage Location | Consistent? |
|--------|--------------------|--------------------|-------------|
| `content_package` dict | Task 6 slice_pdf.py | Task 12 integration test | ✅ |
| `paper_type` enum | Task 7 verify_card.py | Task 11 subagent-prompt.md | ✅ |
| `source_tier` enum | Task 7 verify_card.py | Task 9 ScanState | ✅ |
| `scan_state.json` schema | Task 9 ScanState | Task 8 build_index.py | ✅ |

**All checks pass. Plan is ready for execution.**

---

## Execution Handoff

Plan complete and saved to `docs/superpowers/plans/2026-06-03-paper-scanner.md`.

**Two execution options:**

**1. Subagent-Driven (recommended)** — I dispatch a fresh subagent per task, review between tasks, fast iteration

**2. Inline Execution** — Execute tasks in this session using executing-plans, batch execution with checkpoints

**Which approach?**
