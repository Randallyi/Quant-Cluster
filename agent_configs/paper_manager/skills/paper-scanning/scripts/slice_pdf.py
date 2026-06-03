from typing import List, Dict

import fitz


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
