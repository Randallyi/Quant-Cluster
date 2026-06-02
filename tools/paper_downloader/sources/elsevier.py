import requests
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import List
from sources.base import Source
from core.models import PaperMeta
from core.downloader import download_file, PaywalledError, DownloadError

ELSEVIER_SEARCH = "https://api.elsevier.com/content/search/scopus"
ELSEVIER_ARTICLE = "https://api.elsevier.com/content/article/doi/{doi}?httpAccept=application/pdf&view=FULL"


class ElsevierSource(Source):
    """Elsevier Scopus Search + Article Retrieval API"""
    
    def __init__(self, api_key: str, journals: List[str], year_from: int = 2010):
        self.api_key = api_key
        self.journals = journals
        self.year_from = year_from
        self.name = "elsevier"
        self.frequency = "monthly"
        self.rate_limit_delay = 0.5
    
    def _headers(self):
        return {"X-ELS-APIKey": self.api_key}
    
    def scan(self, since: datetime) -> List[PaperMeta]:
        metas = []
        since_year = max(since.year, self.year_from)
        
        for journal in self.journals:
            start = 0
            while True:
                query = f'SRCTITLE("{journal}") AND openaccess(1) AND PUBYEAR > {since_year - 1}'
                params = {"query": query, "count": 25, "start": start, "sort": "-pubyear"}
                resp = requests.get(ELSEVIER_SEARCH, headers=self._headers(), params=params, timeout=30)
                resp.raise_for_status()
                data = resp.json()
                entries = data.get("search-results", {}).get("entry", [])
                if not entries or (len(entries) == 1 and "error" in entries[0]):
                    break
                
                for entry in entries:
                    if "error" in entry:
                        continue
                    doi = entry.get("prism:doi")
                    title = entry.get("dc:title", "")
                    year = int(entry.get("prism:coverDate", "0")[:4]) if entry.get("prism:coverDate") else None
                    
                    metas.append(PaperMeta(
                        source=self.name,
                        source_id=doi or entry.get("eid", ""),
                        doi=doi,
                        title=title,
                        authors=[],
                        published_at=datetime(year, 1, 1, tzinfo=timezone.utc) if year else None,
                        year=year,
                        landing_url=entry.get("prism:url"),
                    ))
                
                start += len(entries)
                time.sleep(self.rate_limit_delay)
                if len(entries) < 25:
                    break
        return metas
    
    def download(self, meta: PaperMeta, dest_path: Path) -> Path:
        if not meta.doi:
            raise PaywalledError(f"No DOI for Elsevier paper {meta.source_id}")
        url = ELSEVIER_ARTICLE.format(doi=meta.doi)
        headers = self._headers()

        try:
            return download_file(url, dest_path, headers=headers, rate_limit_delay=self.rate_limit_delay)
        except DownloadError as e:
            # Some OA papers return 400 INVALID_INPUT with view=FULL;
            # retry without the view parameter.
            err_msg = str(e)
            if "400" in err_msg and "view=FULL" in url:
                url_no_view = url.replace("&view=FULL", "")
                return download_file(url_no_view, dest_path, headers=headers, rate_limit_delay=self.rate_limit_delay)
            # If content is not a PDF, likely paywalled or API lacks full-text access
            if "not a PDF" in err_msg:
                raise PaywalledError(f"No PDF access for {meta.doi}") from e
            raise
