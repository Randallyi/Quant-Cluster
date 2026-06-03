# Preprocessing Guide

This guide documents how to use `slice_pdf.py` to extract structured content from academic PDFs before dispatching to Subagents.

---

## Basic Usage

### Python API

```python
from pathlib import Path
from scripts.slice_pdf import slice_pdf

package = slice_pdf(
    pdf_path="/workspace/papers/raw/arxiv_2401_12345.pdf",
    output_dir=Path("/workspace/papers/scanned/arxiv_2401_12345/figures"),
)
```

If `output_dir` is omitted, `slice_pdf` navigates upward from the PDF path to find a directory named `papers`, then writes figures to `papers/scanned/{doc_id}/figures/`.

### CLI (via Python module)

```bash
cd /workspace/tools/paper_scanner
python3 -m scripts.slice_pdf \
  --input /workspace/papers/raw/arxiv_2401_12345.pdf \
  --output-dir /workspace/papers/scanned/arxiv_2401_12345/
```

> Note: `slice_pdf.py` is designed primarily as a library. For batch processing, wrap it in a script that loops over `scan_state.get_pending()`.

---

## Output Structure

The function returns a dictionary with the following top-level keys:

```json
{
  "doc_id": "arxiv_2401_12345",
  "filepath": "/workspace/papers/raw/arxiv_2401_12345.pdf",
  "core": { ... },
  "empirical": { ... },
  "proofs": { ... },
  "is_likely_quant": true
}
```

### `core` — Always Present

| Key | Type | Description |
|-----|------|-------------|
| `title` | string | Title extracted from first-page font-size heuristics. |
| `abstract` | string | Full text of the Abstract section. |
| `intro` | string | Full text of the Introduction section. |
| `conclusions` | string | Full text of the Conclusion / Conclusions section. |
| `figures` | list[object] | Extracted images with `path`, `page_num`, `width`, `height`. Filtered to min 100×100 px. |
| `figure_captions` | list[object] | Text blocks from sections whose name contains "figure". Each item has `text` and `page_num`. |
| `table_captions` | list[object] | Text blocks from sections whose name contains "table". Each item has `text` and `page_num`. |
| `tables` | list[object] | Structured tables extracted via PyMuPDF's table finder. Each item has `headers`, `rows`, `page_num`. |

### `empirical` — Present Only When `is_likely_quant == true`

| Key | Type | Description |
|-----|------|-------------|
| `data_section` | string | Full text of the Data section. |
| `methodology_section` | string | Full text of the Methodology / Methods / Empirical section. |
| `results_section` | string | Full text of the Results section. |
| `trading_costs` | list[object] | Paragraphs containing "transaction cost", "slippage", or "market impact". Each item has `text`, `keyword`, `section`, `page_num`. |

### `proofs` — Always Present (May Be Empty)

A dictionary mapping section name → list of blocks for any section whose name contains `appendix`, `proof`, or `derivation`.

---

## Content Package Format

Save the return value of `slice_pdf` as a JSON file next to the PDF (or in the scanned output directory) so the Subagent can read it:

```python
import json
from pathlib import Path

out_path = Path(f"/workspace/papers/scanned/{package['doc_id']}/{package['doc_id']}.json")
out_path.parent.mkdir(parents=True, exist_ok=True)
out_path.write_text(json.dumps(package, ensure_ascii=False, indent=2), encoding="utf-8")
```

This package is the **single input** the Subagent needs, along with the original PDF path for fallback figure inspection.

---

## Section Detection Heuristics

`slice_pdf` identifies sections using three rules applied to text blocks:

1. **Known keyword match** — The block text (normalized) matches a known section name (e.g., "abstract", "methodology", "results") and is shorter than 50 characters.
2. **Numbered pattern** — The block matches a numbering prefix (`1.`, `I.`, `(1)`) and the remainder matches a known section name.
3. **All-caps + large font** — The block is all uppercase, contains letters, is shorter than 60 characters, and its font size exceeds 1.2× the median font size of the document.

Known sections include:

```
abstract, introduction, data, methodology, methods, results,
conclusion, conclusions, references, appendix, proof,
acknowledgments, acknowledgements, discussion, literature review,
related work, experimental setup, experiments, evaluation,
background, preliminaries, model, theory
```

### Title Extraction

The title is extracted from the first page by selecting the largest-font text block that:
- Is at least 10 characters long
- Is not one of the excluded keywords (`abstract`, `introduction`, `keywords`, `jel classification`)

---

## Quantitative Detection

A paper is flagged as `is_likely_quant = true` if at least 3 occurrences of the following keywords are found across all text blocks:

```
regression, sharpe ratio, alpha, beta, portfolio,
p-value, t-statistic, correlation, volatility, arbitrage,
risk-adjusted, backtest, factor, empirical, econometric
```

If the count is below 3, `empirical` will be an empty dict and `is_likely_quant` will be `false`. The Subagent should still evaluate the paper and may override `paper_type` based on deeper reading.

---

## Troubleshooting

### Missing Sections

**Symptom:** `core.abstract` or `empirical.methodology_section` is empty.

**Causes & Fixes:**
- The PDF uses non-standard section names (e.g., "Empirical Strategy" instead of "Methodology"). Inspect the raw blocks or add the alias to `KNOWN_SECTIONS` in `slice_pdf.py`.
- The section header uses a font size that falls below the 1.2× median threshold. This can happen in two-column layouts with small section headers. Consider lowering the multiplier for that document class.
- The PDF is scanned (image-only) without OCR text. PyMuPDF cannot extract text from image pages. Pre-OCR the PDF or skip it.

### Bad Title Extraction

**Symptom:** `core.title` is a journal name, author name, or "Abstract".

**Fix:** The heuristic picks the largest font on page 1. Some publishers put the journal logo in a larger font than the title. Manually override the title in the Subagent prompt or adjust the `excluded` set in `extract_title()`.

### Figures Missing

**Symptom:** `core.figures` is empty but the PDF clearly contains charts.

**Causes & Fixes:**
- The figures are vector graphics (drawings) rather than embedded images. PyMuPDF's `get_images()` only captures bitmap images. Vector figures cannot be auto-extracted; the Subagent must rely on the PDF for visual inspection.
- The images are smaller than 100×100 pixels (e.g., inline math glyphs). These are intentionally filtered out.

### Tables Malformed

**Symptom:** `core.tables` has incorrect headers or merged cells.

**Fix:** PyMuPDF's table finder works well for simple grids but struggles with complex layouts (multi-level headers, nested cells). The Subagent should reference the original PDF for critical tables.

### Slow Processing on Large PDFs

**Symptom:** `slice_pdf` takes >30 seconds on a 100-page PDF.

**Fix:**
- Ensure the PDF is local (not on a network mount).
- For batch jobs, run `slice_pdf` in parallel processes (not threads) because `fitz.Document` is not thread-safe.
- If only text is needed and figures are not, temporarily skip `extract_all_figures()` to save time.

### Duplicated Section Names

**Symptom:** Sections dictionary has keys like `appendix_2`, `appendix_3`.

**Explanation:** `identify_sections` deduplicates keys by appending `_2`, `_3`, etc. This is expected when a paper has multiple appendices or proof sections.
