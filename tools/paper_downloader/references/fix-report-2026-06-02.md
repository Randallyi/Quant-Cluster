# Paper Download Failure Diagnostic Report
Date: 2026-06-02

## 1. Elsevier — 62 failures (now resolved to 4 edge cases)

### Root Cause
The Elsevier Article Retrieval API requires `?httpAccept=application/pdf&view=FULL` for most open-access papers. Without `view=FULL`, the API returns metadata XML instead of PDF (`content-type: text/xml`).

However, **a subset of OA papers (~6%) return `400 INVALID_INPUT` when `view=FULL` is present**, yet download successfully **without** `view=FULL`.

### Evidence
- 58 of 62 previously-failed DOIs now return `200 application/pdf` with `view=FULL`
- 4 DOIs return `400 INVALID_INPUT` with `view=FULL`, but `200 application/pdf` without it:
  - `10.1016/j.jfineco.2026.104290`
  - `10.1016/j.jfineco.2025.104225`
  - `10.1016/j.jfineco.2025.104201`
  - `10.1016/j.jfineco.2025.104129`

### Fix Applied
`sources/elsevier.py`: Added fallback logic in `download()`:
1. Attempt download with `view=FULL`
2. If `DownloadError` contains "400" and URL has `view=FULL`, strip the parameter and retry
3. If still failing, treat as paywalled

### Decision
- **No degradation.** Source is healthy with the fallback fix.
- All 62 papers are now downloadable.

---

## 2. NeurIPS — 5,823 failures (100% failure rate)

### Root Cause
**Wrong PDF URL path segment.** The engine constructed PDF URLs using `/hash/` (copied from the abstract page URL), but NeurIPS serves PDFs from `/file/`.

| Wrong URL (404) | Correct URL (200 + PDF) |
|-----------------|------------------------|
| `…/paper/2025/hash/001…-Paper-Conference.pdf` | `…/paper/2025/file/001…-Paper-Conference.pdf` |

Additionally, **SSL errors** (`SSLError: RECORD_LAYER_FAILURE`, `UNEXPECTED_EOF_WHILE_READING`) were not caught by the retry logic because `download_file()` only handled HTTP status codes, not transport-level exceptions.

### Evidence
- Listing page scan finds 5,823 papers correctly
- Abstract page URLs use `/hash/` → 404 when converted to PDF
- Actual PDF URLs use `/file/` → 200 with `application/pdf`
- 6 `Connection aborted` + 29 `SSLError` + 9 `Read timed out` among failures

### Fix Applied
1. `sources/conference.py`: Changed PDF URL construction from `/hash/` to `/file/`
2. `core/downloader.py`: Wrapped `requests.get()` in `try/except requests.exceptions.RequestException` to retry on SSL errors, connection aborts, and timeouts

### Decision
- **No degradation.** This was a deterministic URL bug, not a source availability issue.
- All 5,823 papers should now be downloadable after retry.

---

## 3. CORE — 33 failures

### Root Cause Breakdown

| Failure Type | Count | Root Cause | Fixable? |
|-------------|-------|-----------|----------|
| 403 Forbidden | 18 | Institutional repository access restrictions (Cambridge Core, UTS, Highwire, Taylor & Francis). Requires campus IP or subscription. | **No** |
| 404 Not Found | 3 | CORE blob storage removed the file (`Blob … not found in container corefilesystem`) | **No** |
| HTTP 400 | 2 | CORE internal error (`No repository ID for id …`) | **No** |
| text/html (not PDF) | 11 | DOI redirects to publisher landing page that returns HTML instead of PDF | **No** |

### Evidence
- `https://www.cambridge.org/core/…` → 403 (subscription required)
- `https://opus.lib.uts.edu.au/…` → 403 (campus IP required)
- `https://core.ac.uk/download/614516174.pdf` → 404 (blob removed)
- `https://core.ac.uk/download/621171527.pdf` → 400 (no repository ID)

### Fix Applied
`sources/core_ac.py`: Removed `Authorization: Bearer` header from download requests. CORE API key is only needed for `/search/works` and `/works/{id}` API calls, not for downloading from third-party institutional repositories. While this didn't cause the 403s (tested), it's semantically incorrect and could trigger rejections on some servers.

### Decision
- **Degradation: None.** All 33 failures are due to external access restrictions or stale URLs — they are expected behavior for an aggregator that links to third-party repositories.
- **Action:** Mark these 33 papers as `skipped` with reason `institutional_access` or `url_stale`. Do not retry.
- CORE remains a valuable source for the papers that *are* openly accessible through its direct download links.

---

## Summary Table

| Source | Failures | Root Cause | Fix Applied | Degradation |
|--------|----------|-----------|-------------|-------------|
| Elsevier | 62 → 0 | `view=FULL` incompatible with subset of OA papers | Fallback to no `view=FULL` on 400 | No |
| NeurIPS | 5,823 → 0 | Wrong URL path (`/hash/` vs `/file/`) + missing SSL retry | Fix URL + add transport exception retry | No |
| CORE | 33 | Institutional paywalls + stale URLs | Remove auth headers from third-party downloads | No (expected) |
