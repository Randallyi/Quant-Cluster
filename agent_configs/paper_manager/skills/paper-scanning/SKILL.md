---
name: paper-scanning
description: |
  Deep-reads academic PDFs from the local paper pool and produces structured
  paper cards with methodology audits for quantitative papers. Triggered when
  the user says "scan papers", "read papers", "analyze downloaded papers",
  or "update paper cards".
---

# Paper Scanning

## Quick Start

Scan all unprocessed papers:

```bash
cd /workspace/tools/paper_scanner
python3 -m scripts.slice_pdf --input PDF --output-dir DIR
```

## Workflow

Copy this checklist and track progress:

```
Paper Scanning Progress:
- [ ] Step 0: Pre-flight (check raw/ directory, scan_state.json)
- [ ] Step 1: Build pending queue from scan_state
- [ ] Step 2: Preprocess PDFs with slice_pdf.py
- [ ] Step 3: Dispatch Subagent for each paper (max 3 concurrent)
- [ ] Step 4: Collect Subagent results
- [ ] Step 5: Assemble card.md + card_en.md
- [ ] Step 6: Verify card format
- [ ] Step 7: Update scan_state + build_index
- [ ] Step 8: Generate report + checkpoint
```

**Step 0: Pre-flight**

Check that the paper pool directory exists and `scan_state.json` is readable:

```bash
ls /workspace/papers/raw/
cat /workspace/papers/scan_state.json | python3 -m json.tool
```

If `scan_state.json` is missing, `ScanState` will auto-initialize it with default config (`max_concurrent: 3`).

**Step 1: Build pending queue**

Use `scan_state.get_pending()` to retrieve papers in priority order:

```python
from scripts.scan_state import ScanState
state = ScanState(Path("/workspace/papers/scan_state.json"))
queue = state.get_pending()  # sorted by source_tier > year_desc
```

**Step 2: Preprocess PDFs**

For each pending paper, run `slice_pdf` to extract text blocks, sections, figures, tables, and keyword hits:

```python
from scripts.slice_pdf import slice_pdf
package = slice_pdf("/workspace/papers/raw/arxiv_1234.pdf")
```

The package contains `core`, `empirical`, `proofs`, and `is_likely_quant`. Save it as `{doc_id}.json` next to the PDF for the Subagent to consume.

**Step 3: Dispatch Subagent**

Launch up to 3 concurrent Subagents. Each Subagent receives:
- The preprocessing package (`{doc_id}.json`)
- The original PDF path
- The system prompt from [references/subagent-prompt.md](references/subagent-prompt.md)

Pass `--max-concurrent 3` or enforce it in the dispatcher loop.

**Step 4: Collect Subagent results**

Each Subagent returns a JSON blob matching the schema in [references/subagent-prompt.md](references/subagent-prompt.md). Store the raw JSON as `{doc_id}_result.json`.

**Step 5: Assemble card.md + card_en.md**

Render the Subagent JSON into bilingual cards using the templates in [references/card-template.md](references/card-template.md).

- Chinese card → `scanned/{doc_id}/card.md`
- English card → `scanned/{doc_id}/card_en.md`

**Step 6: Verify card format**

Run `verify_card` against both cards:

```python
from scripts.verify_card import verify_card
result = verify_card(Path(f"scanned/{doc_id}/card.md"))
assert result["valid"], result["errors"]
```

Checks include: required frontmatter fields, `source_tier` / `paper_type` enums, and mandatory quantitative sections when `paper_type == "quantitative"`.

**Step 7: Update scan_state + build_index**

```python
state.mark_status(doc_id, "completed", card_data=result_json)
```

Then regenerate the index:

```python
from scripts.build_index import build_index
build_index(
    Path("/workspace/papers/scan_state.json"),
    Path("/workspace/papers/scanned/index.json"),
)
```

**Step 8: Generate report + checkpoint**

Produce a bilingual report summarizing:
- Papers scanned this round (doc_id, title, credibility_score, credibility_tier)
- Quantitative vs non-quantitative breakdown
- Methodology red flags or high-value findings
- Failures with reason

Write `.agent_checkpoint.json` with `{"status": "completed", "round": N}`.

## Scripts Reference

| Script | Purpose | Example |
|--------|---------|---------|
| `slice_pdf.py` | Extract structured content (text, sections, figures, tables) from a PDF and flag likely quantitative papers. | `python3 -m scripts.slice_pdf --input paper.pdf --output-dir scanned/paper_id/` |
| `verify_card.py` | Validate `card.md` frontmatter and section structure against the spec. | `python3 -m scripts.verify_card scanned/paper_id/card.md` |
| `build_index.py` | Generate `scanned/index.json` from `scan_state.json` for fast lookups and stats. | `python3 -m scripts.build_index scan_state.json scanned/index.json` |
| `scan_state.py` | CRUD for scan progress. Tracks `pending → preprocessing → scanning → completed/failed/skipped`. | `from scripts.scan_state import ScanState; state = ScanState(path)` |

## Subagent Prompt

See [references/subagent-prompt.md](references/subagent-prompt.md) for the full system prompt, rules, JSON output schema, and credibility scoring rubric.

## Card Templates

See [references/card-template.md](references/card-template.md) for the exact bilingual card frontmatter and section templates.

## Preprocessing Guide

See [references/preprocessing-guide.md](references/preprocessing-guide.md) for detailed `slice_pdf.py` usage, output structure, content package format, and troubleshooting.

## Engine Boundary

- **Scripts do**: PDF parsing, section heuristics, figure/table extraction, state management, index generation, card validation
- **Agent / Subagent does**: semantic analysis, methodology audit, credibility scoring, card authoring, bilingual translation
- **Never do**: modify `slice_pdf.py` heuristics for a single paper; if a class of PDFs consistently fails section detection, patch the script and re-test on a sample

## Output Naming Convention

| Artifact | Path |
|----------|------|
| Chinese card | `scanned/{doc_id}/card.md` |
| English card | `scanned/{doc_id}/card_en.md` |
| Preprocessing package | `scanned/{doc_id}/{doc_id}.json` |
| Subagent raw result | `scanned/{doc_id}/{doc_id}_result.json` |
| Scan state | `papers/scan_state.json` |
| Index | `papers/scanned/index.json` |
| Checkpoint | `.agent_checkpoint.json` |
