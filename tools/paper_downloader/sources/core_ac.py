import requests
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import List
from sources.base import Source
from core.models import PaperMeta
from core.downloader import download_file, DownloadError

CORE_API = "https://api.core.ac.uk/v3"


class CoreSource(Source):
    """CORE API v3: search Works → get Outputs → download via downloadUrl"""
    
    def __init__(self, api_key: str, queries: List[str], year_from: int = 2010):
        self.api_key = api_key
        self.queries = queries
        self.year_from = year_from
        self.name = "core_ac"
        self.frequency = "monthly"
        self.rate_limit_delay = 2.4  # 25 req/min for registered users
    
    def _headers(self):
        return {"Authorization": f"Bearer {self.api_key}"}
    
    def scan(self, since: datetime) -> List[PaperMeta]:
        metas = []
        # CORE data has latency; use year_from from config rather than since.year
        # dedupe_and_insert() will skip already-known papers
        query_str = " OR ".join(f"({q})" for q in self.queries)
        full_query = f'({query_str}) AND yearPublished>={self.year_from}'
        
        offset = 0
        while True:
            params = {"q": full_query, "limit": 100, "offset": offset, "sort": "recency"}
            resp = requests.get(f"{CORE_API}/search/works", headers=self._headers(), params=params, timeout=30)
            resp.raise_for_status()
            data = resp.json()
            results = data.get("results", [])
            if not results:
                break
            
            for work in results:
                year = work.get("yearPublished")
                published = datetime(year, 1, 1, tzinfo=timezone.utc) if year else datetime.now(timezone.utc)
                # NOTE: CORE data has latency (often 1+ years behind). Do NOT filter by
                # `published < since` here — the query already uses `yearPublished>=year_from`
                # and dedupe_and_insert() handles duplicates. Filtering by `since` would
                # silently drop all papers when CORE hasn't caught up to the current year.
                
                doi = work.get("doi")
                work_id = work.get("id")
                
                # Get downloadUrl directly from search results
                pdf_url = work.get("downloadUrl")
                
                # Skip if no download URL available
                if not pdf_url:
                    continue
                
                metas.append(PaperMeta(
                    source=self.name,
                    source_id=str(work_id),
                    doi=doi,
                    title=work.get("title", ""),
                    authors=work.get("authors", []),
                    abstract=work.get("abstract"),
                    published_at=published,
                    year=year,
                    pdf_url=pdf_url,
                    landing_url=work.get("links", [{}])[0].get("url") if work.get("links") else None,
                ))
            
            offset += len(results)
            time.sleep(self.rate_limit_delay)
            if len(results) < 100:
                break
        return metas
    
    def download(self, meta: PaperMeta, dest_path: Path) -> Path:
        if not meta.pdf_url:
            raise DownloadError(f"No pdf_url for CORE work {meta.source_id}")
        # Do NOT pass CORE API auth headers to third-party repository URLs;
        # they may cause unexpected 403s or be ignored.
        return download_file(meta.pdf_url, dest_path, rate_limit_delay=self.rate_limit_delay)
