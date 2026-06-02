# Paper Asset Management Report 2026-06-02

## Executive Summary

The engine is currently in a **degraded** state. The overall failure rate is 97%, driven almost entirely by the `neurips_2025` source (5,823 404 failures). Excluding that source, the actual failure rate is 28% (97 / 345), still above the healthy threshold.

| Metric | Value |
|--------|-------|
| Total downloaded | 170 |
| Total failed | 5,920 |
| Healthy sources | 2 (arxiv_qfin_tr, arxiv_cs_lg) |
| Degraded sources | 3 (core_ac, elsevier, neurips_2025) |
| Pending | 0 |

---

## Per-Source Status

### arxiv_qfin_tr — Healthy
- Downloaded: 129
- Failed: 1 (0.8%)
- Decision: No action needed

### arxiv_cs_lg — Healthy
- Downloaded: 4
- Failed: 0
- Decision: No action needed

### core_ac — Degraded
- Downloaded: 19
- Failed: 33 (63%)
- Failure reason: Returns HTML instead of PDF; some 400/404 errors
- Decision: Check CORE_API_KEY then retry once. If still >50% failure, disable.

### elsevier — Degraded
- Downloaded: 17
- Failed: 62 (78%)
- Failure reason: API returns XML instead of PDF (likely auth failure or paywall)
- Decision: Check ELSEVIER_API_KEY then retry once. If still >50% failure, disable.

### wiley — Marginal
- Downloaded: 1
- Failed: 1 (50%)
- Decision: Insufficient sample size, continue observing

### neurips_2025 — Completely Broken
- Downloaded: 0
- Failed: 5,823 (100%)
- Failure reason: 5,771 x 404 Not Found, 37 x SSL/connection timeouts. NeurIPS 2025 has not yet occurred (typically December), PDFs are not published.
- Decision: **Disable immediately**. Purge 5,823 failed records from the database. No retry value.

---

## Failure Analysis

### neurips_2025 Root Cause
`NeurIPSSource` constructs the year using `datetime.now().year - 1`, yielding 2025 (indicating the current year is recognized as 2026). NeurIPS 2025 papers have not been published, so all PDF URLs return 404.

This is not a network failure — the data source simply does not exist yet. The source should be disabled and re-enabled after the December 2025 conference concludes.

### elsevier Root Cause
All 62 failures show `content-type: text/xml`. The Elsevier API returns XML error responses when authentication fails or when requesting non-open-access papers. Need to verify API key validity and ensure the journal list consists of OA titles.

### core_ac Root Cause
Most failures return HTML (likely a login or error page), with a few 400/404 errors. The CORE API key may be invalid, or the PDF links in query results may have expired.

---

## Decision Log

| Source | Decision | Rationale |
|--------|----------|-----------|
| neurips_2025 | **Disable + purge DB** | Conference has not occurred; 5,823 records are invalid noise |
| elsevier | Check API key then retry | Consistent failure pattern (XML); likely fixable |
| core_ac | Check API key then retry | Consistent failure pattern (HTML); likely fixable |
| wiley | Keep observing | Insufficient sample size |
| arxiv_* | No action | Running healthy |

---

## Next Steps

1. Set `neurips.enabled` to `false` in `config.yaml`
2. Delete all records with `source='neurips_2025'` from the database
3. Verify that `CORE_API_KEY` and `ELSEVIER_API_KEY` environment variables are valid
4. Run a single-source scan test for elsevier and core_ac
5. If post-retry failure rate remains >30%, mark the corresponding source as disabled

---

## Engine Issue

`paper_downloader/__main__.py` uses absolute imports (`from core.store import ...`), which requires `/workspace/tools/paper_downloader` to be on `PYTHONPATH` at runtime. The correct invocation is currently:

```bash
PYTHONPATH=/workspace/tools/paper_downloader:/workspace/tools python -m paper_downloader stats
```

Recommended fix: switch to relative imports or handle package paths internally.
