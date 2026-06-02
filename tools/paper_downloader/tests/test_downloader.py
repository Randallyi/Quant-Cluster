import sys, os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..'))

import tempfile
from pathlib import Path
from unittest.mock import patch, MagicMock

import pytest

from core.downloader import download_file, DownloadError, PaywalledError


class MockResponse:
    def __init__(self, status_code, content=b"", headers=None, raw=None):
        self.status_code = status_code
        self.content = content
        self.headers = headers or {}
        self.raw = raw or MagicMock()

    def iter_content(self, chunk_size=1024):
        for i in range(0, len(self.content), chunk_size):
            yield self.content[i:i + chunk_size]

    def raise_for_status(self):
        if self.status_code >= 400:
            from requests import HTTPError
            raise HTTPError(f"{self.status_code} Error", response=self)


def test_download_success():
    pdf_content = b"%PDF-1.4 test content"
    response = MockResponse(
        200,
        content=pdf_content,
        headers={"content-type": "application/pdf"},
    )

    with tempfile.TemporaryDirectory() as tmpdir:
        dest = Path(tmpdir) / "subdir" / "paper.pdf"

        with patch("core.downloader.requests.get", return_value=response) as mock_get:
            with patch("core.downloader.time.sleep") as mock_sleep:
                result = download_file(
                    "http://example.com/paper.pdf",
                    dest,
                    rate_limit_delay=0.0,
                )

        assert result == dest
        assert dest.exists()
        assert dest.read_bytes() == pdf_content
        mock_get.assert_called_once()
        mock_sleep.assert_called_once_with(0.0)


def test_download_non_pdf_detected():
    html_content = b"<html><body>Not a PDF</body></html>"
    response = MockResponse(
        200,
        content=html_content,
        headers={"content-type": "text/html; charset=utf-8"},
    )

    with tempfile.TemporaryDirectory() as tmpdir:
        dest = Path(tmpdir) / "paper.pdf"

        with patch("core.downloader.requests.get", return_value=response):
            with pytest.raises(DownloadError) as exc_info:
                download_file(
                    "http://example.com/paper.pdf",
                    dest,
                    rate_limit_delay=0.0,
                )

        assert "not a pdf" in str(exc_info.value).lower()
        assert not dest.exists()


def test_download_retries_on_500():
    pdf_content = b"%PDF-1.4 test content"
    fail_response = MockResponse(
        500,
        headers={},
    )
    success_response = MockResponse(
        200,
        content=pdf_content,
        headers={"content-type": "application/pdf"},
    )

    with tempfile.TemporaryDirectory() as tmpdir:
        dest = Path(tmpdir) / "paper.pdf"

        with patch(
            "core.downloader.requests.get",
            side_effect=[fail_response, success_response],
        ) as mock_get:
            with patch("core.downloader.time.sleep") as mock_sleep:
                result = download_file(
                    "http://example.com/paper.pdf",
                    dest,
                    rate_limit_delay=0.1,
                    max_retries=3,
                )

        assert result == dest
        assert dest.exists()
        assert dest.read_bytes() == pdf_content
        assert mock_get.call_count == 2
        # First retry backoff: 0.1 * (2 ** 0) = 0.1, then success sleep 0.1
        mock_sleep.assert_any_call(0.1)
