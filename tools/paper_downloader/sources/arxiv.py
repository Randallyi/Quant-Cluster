import requests
import time
import xml.etree.ElementTree as ET
from datetime import datetime, timezone
from pathlib import Path
from typing import List

from sources.base import Source
from core.models import PaperMeta
from core.downloader import download_file

ARXIV_API = "https://export.arxiv.org/api/query"
ARXIV_PDF = "https://arxiv.org/pdf/{id}.pdf"
GCS_BASE = "https://storage.googleapis.com/arxiv-dataset"


def parse_arxiv_id(url: str) -> str:
    """Extract arXiv ID from URL."""
    url = url.rstrip("/")
    if "/abs/" in url:
        return url.split("/abs/")[-1]
    return url.split("/")[-1]


class ArxivSource(Source):
    """arXiv source: incremental via API, bulk backfill via GCS."""

    def __init__(self, category: str, backfill_mode: str = "api"):
        self.category = category
        self.name = f"arxiv_{category.replace('-', '').replace('.', '_').lower()}"
        self.frequency = "weekly"
        self.rate_limit_delay = 3.0
        self.backfill_mode = backfill_mode

    def scan(self, since: datetime) -> List[PaperMeta]:
        """Incremental scan via API. GCS backfill is a separate operation."""
        return self._scan_api(since)

    def _scan_api(self, since: datetime) -> List[PaperMeta]:
        """Fetch incremental papers via arXiv API."""
        metas = []
        start = 0
        while True:
            params = {
                "search_query": f"cat:{self.category}",
                "sortBy": "submittedDate",
                "sortOrder": "descending",
                "start": start,
                "max_results": 100,
            }
            resp = requests.get(ARXIV_API, params=params, timeout=60)
            resp.raise_for_status()
            root = ET.fromstring(resp.content)
            ns = {"atom": "http://www.w3.org/2005/Atom"}
            entries = root.findall(".//atom:entry", ns)
            if not entries:
                break
            for entry in entries:
                id_elem = entry.find("atom:id", ns)
                title_elem = entry.find("atom:title", ns)
                summary_elem = entry.find("atom:summary", ns)
                published_elem = entry.find("atom:published", ns)

                arxiv_id = parse_arxiv_id(id_elem.text) if id_elem is not None else ""
                published = datetime.fromisoformat(published_elem.text.replace("Z", "+00:00")) if published_elem is not None else datetime.now(timezone.utc)
                since_aware = since.replace(tzinfo=timezone.utc) if since.tzinfo is None else since
                if published < since_aware:
                    return metas

                authors = []
                for author in entry.findall("atom:author", ns):
                    name = author.find("atom:name", ns)
                    if name is not None:
                        authors.append(name.text)

                pdf_link = entry.find('.//atom:link[@title="pdf"]', ns)
                pdf_url = pdf_link.get("href") if pdf_link is not None else ARXIV_PDF.format(id=arxiv_id)

                metas.append(PaperMeta(
                    source=self.name,
                    source_id=arxiv_id,
                    title=title_elem.text.strip() if title_elem is not None else "",
                    authors=authors,
                    abstract=summary_elem.text.strip() if summary_elem is not None else None,
                    published_at=published,
                    year=published.year,
                    pdf_url=pdf_url,
                    landing_url=id_elem.text if id_elem is not None else None,
                ))
            start += len(entries)
            time.sleep(self.rate_limit_delay)
        return metas

    def _scan_gcs(self, since: datetime) -> List[PaperMeta]:
        """Bulk backfill via GCS public bucket listing."""
        metas = []
        year_from = since.year
        year_to = datetime.now().year
        for year in range(year_from, year_to + 1):
            for month in range(1, 13):
                prefix = f"arxiv/arxiv/pdf/{year:02d}{month:02d}/"
                url = f"{GCS_BASE}?prefix={prefix}&max-keys=1000"
                resp = requests.get(url, timeout=30)
                if resp.status_code != 200:
                    continue
                root = ET.fromstring(resp.content)
                ns = {"s3": "http://doc.s3.amazonaws.com/2006-03-01"}
                for key in root.findall(".//s3:Key", ns):
                    key_text = key.text
                    if not key_text.endswith(".pdf"):
                        continue
                    filename = key_text.split("/")[-1]
                    arxiv_id = filename.replace(".pdf", "")
                    yymm = prefix.split("/")[-2]
                    year_num = 2000 + int(yymm[:2])
                    month_num = int(yymm[2:])
                    published = datetime(year_num, month_num, 1)
                    if published < since:
                        continue
                    metas.append(PaperMeta(
                        source=self.name,
                        source_id=arxiv_id,
                        title="",
                        published_at=published,
                        year=year_num,
                        pdf_url=f"{GCS_BASE}/{key_text}",
                    ))
        return metas

    def download(self, meta: PaperMeta, dest_path: Path) -> Path:
        url = meta.pdf_url or ARXIV_PDF.format(id=meta.source_id)
        return download_file(url, dest_path, rate_limit_delay=self.rate_limit_delay)
