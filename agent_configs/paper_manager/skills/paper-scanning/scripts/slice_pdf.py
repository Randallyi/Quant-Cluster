import re
import statistics
from typing import List, Dict

import fitz


KNOWN_SECTIONS = {
    "abstract",
    "introduction",
    "data",
    "methodology",
    "methods",
    "results",
    "conclusion",
    "conclusions",
    "references",
    "appendix",
    "proof",
    "acknowledgments",
    "acknowledgements",
    "discussion",
    "literature review",
    "related work",
    "experimental setup",
    "experiments",
    "evaluation",
    "background",
    "preliminaries",
    "model",
    "theory",
}

_NUMBERED_RE = re.compile(
    r"^\s*(?:\d+\.|[IVXivx]+\.|\(\d+\))\s*(.+)$"
)


def extract_text_blocks_with_fonts(doc: fitz.Document) -> List[Dict]:
    """Extract all text blocks from all pages with their max font size."""
    blocks = []
    for page_num in range(doc.page_count):
        page = doc.load_page(page_num)
        text_dict = page.get_text("dict")
        for block in text_dict.get("blocks", []):
            if block.get("type") != 0:
                continue
            max_font_size = 0.0
            text_parts = []
            for line in block.get("lines", []):
                for span in line.get("spans", []):
                    max_font_size = max(max_font_size, span.get("size", 0.0))
                    text_parts.append(span.get("text", ""))
            text = "".join(text_parts).strip()
            if not text:
                continue
            blocks.append({
                "text": text,
                "font_size": float(max_font_size),
                "page_num": page_num + 1,
                "bbox": list(block.get("bbox", [])),
            })
    return blocks


def extract_title(blocks: List[Dict]) -> str:
    """Extract paper title from first-page blocks using font-size heuristic."""
    first_page_blocks = [b for b in blocks if b["page_num"] == 1]
    if not first_page_blocks:
        return ""

    excluded = {"abstract", "introduction", "keywords", "jel classification"}

    # Sort by font size descending
    sorted_blocks = sorted(first_page_blocks, key=lambda b: b["font_size"], reverse=True)

    for block in sorted_blocks:
        text = block["text"]
        if len(text) < 10:
            continue
        if text.lower() in excluded:
            continue
        return text

    # Fallback: return the text from the largest-font block on first page
    return sorted_blocks[0]["text"] if sorted_blocks else ""


def _normalize_section_name(text: str) -> str:
    """Strip punctuation/whitespace and lower-case a section header."""
    return text.strip().strip(":.-–—").lower()


def _is_section_header(block: Dict, median_font_size: float) -> bool:
    """Return True if *block* looks like a section header."""
    text = block["text"].strip()
    if not text:
        return False

    # Rule 1: Known keyword match
    normalized = _normalize_section_name(text)
    if normalized in KNOWN_SECTIONS and len(text) < 50:
        return True

    # Rule 2: Numbered pattern (e.g. "1. Introduction", "I. INTRODUCTION", "(1) Methodology")
    match = _NUMBERED_RE.match(text)
    if match and len(text) < 50:
        section_name = _normalize_section_name(match.group(1))
        if section_name in KNOWN_SECTIONS:
            return True

    # Rule 3: All caps + large font
    if (
        text == text.upper()
        and text != text.lower()  # ensure there are letters
        and len(text) < 60
        and block["font_size"] > 1.2 * median_font_size
    ):
        return True

    return False


def identify_sections(blocks: List[Dict]) -> Dict[str, List[Dict]]:
    """Heuristically identify section headers and group blocks into sections."""
    if not blocks:
        return {}

    median_font_size = statistics.median(b["font_size"] for b in blocks)

    sections: Dict[str, List[Dict]] = {}
    current_name: str | None = None
    current_blocks: List[Dict] = []

    for block in blocks:
        if _is_section_header(block, median_font_size):
            # Save the previous section
            if current_name is not None:
                sections[current_name] = current_blocks

            # Start a new section
            current_name = _normalize_section_name(block["text"])
            # Deduplicate keys
            original = current_name
            counter = 2
            while current_name in sections:
                current_name = f"{original}_{counter}"
                counter += 1

            current_blocks = [block]
        else:
            current_blocks.append(block)

    # Save the last section
    if current_name is not None:
        sections[current_name] = current_blocks

    return sections


def extract_section(sections: Dict, *names: str) -> str:
    """Extract text content from a section by name (case-insensitive)."""
    for key in sections:
        for name in names:
            if key.lower() == name.lower():
                content_blocks = sections[key][1:]  # skip header block
                return "\n".join(b["text"] for b in content_blocks)
    return ""
