"""Unified HTTP download module with retry logic and PDF validation."""

import time
from pathlib import Path
from typing import Optional, Dict

import requests


class DownloadError(Exception):
    """General download failure."""
    pass


class PaywalledError(DownloadError):
    """403/paywalled content — should NOT be retried."""
    pass


def download_file(
    url: str,
    dest_path: Path,
    headers: Optional[Dict[str, str]] = None,
    rate_limit_delay: float = 1.0,
    max_retries: int = 3,
    timeout: int = 30,
) -> Path:
    """
    Download a file from *url* to *dest_path*.

    Returns *dest_path* on success.

    Raises:
        PaywalledError: on HTTP 403 (do not retry).
        DownloadError: on HTTP 404 or when the content is not a valid PDF.
    """
    dest_path = Path(dest_path)
    dest_path.parent.mkdir(parents=True, exist_ok=True)

    attempt = 0
    while True:
        try:
            response = requests.get(
                url,
                headers=headers,
                stream=True,
                timeout=timeout,
            )
        except requests.exceptions.RequestException as exc:
            # Catch connection errors, SSL errors, timeouts, etc.
            if attempt >= max_retries:
                raise DownloadError(f"Network error after {max_retries} retries: {url} — {exc}")
            time.sleep(rate_limit_delay * (2 ** attempt))
            attempt += 1
            continue

        # HTTP status handling
        if response.status_code == 403:
            raise PaywalledError(f"403 Forbidden (paywalled): {url}")

        if response.status_code == 404:
            raise DownloadError(f"404 Not Found: {url}")

        if response.status_code == 429:
            retry_after = float(
                response.headers.get("Retry-After", rate_limit_delay * 5)
            )
            time.sleep(retry_after)
            continue  # does not count against max_retries

        if response.status_code >= 400:
            if attempt >= max_retries:
                raise DownloadError(
                    f"HTTP {response.status_code} after {max_retries} retries: {url}"
                )
            time.sleep(rate_limit_delay * (2 ** attempt))
            attempt += 1
            continue

        # Success path — validate and save
        first_bytes = b""
        with open(dest_path, "wb") as f:
            for chunk in response.iter_content(chunk_size=8192):
                if chunk:
                    if not first_bytes:
                        first_bytes = chunk
                    f.write(chunk)

        # PDF validation
        is_pdf_magic = first_bytes.startswith(b"%PDF")
        content_type = response.headers.get("content-type", "").lower()
        is_pdf_ct = "pdf" in content_type

        if not is_pdf_magic and not is_pdf_ct:
            dest_path.unlink(missing_ok=True)
            raise DownloadError(
                f"Downloaded content is not a PDF (content-type: {content_type or 'unknown'})"
            )

        # Rate-limit sleep after successful download
        time.sleep(rate_limit_delay)
        return dest_path
