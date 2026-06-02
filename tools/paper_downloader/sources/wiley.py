import requests
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import List
from sources.base import Source
from core.models import PaperMeta
from core.downloader import download_file, PaywalledError

CROSSREF_API = "https://api.crossref.org/works"
WILEY_TDM = "https://api.wiley.com/onlinelibrary/tdm/v1/articles/{doi}"


class WileySource(Source):
    """Wiley: Crossref discovery (CC-BY filter) + TDM API download"""
    
    def __init__(self, tdm_token: str, journals: List[str], year_from: int = 2010, max_results: int = 500):
        self.tdm_token = tdm_token
        self.journals = journals
        self.year_from = year_from
        self.max_results = max_results
        self.name = "wiley"
        self.frequency = "monthly"
        self.rate_limit_delay = 0.35
    
    def scan(self, since: datetime) -> List[PaperMeta]:
        metas = []
        offset = 0
        journal_filter = " OR ".join(f'"{j}"' for j in self.journals)
        since_date = max(since.year, self.year_from)
        
        while True:
            params = {
                "filter": f"member:311,from-pub-date:{since_date}-01-01",
                "query.container-title": journal_filter,
                "rows": 100,
                "offset": offset,
                "sort": "published",
                "order": "desc",
            }
            resp = requests.get(CROSSREF_API, params=params, timeout=30)
            resp.raise_for_status()
            data = resp.json()
            items = data.get("message", {}).get("items", [])
            if not items:
                break
            
            for item in items:
                # Skip non-articles (journal issues, etc.)
                if item.get("type") != "journal-article":
                    continue
                # Exact journal match — CrossRef query is fuzzy, so we filter results
                container_titles = item.get("container-title", []) or []
                if not any(
                    ct.lower() == j.lower()
                    for ct in container_titles
                    for j in self.journals
                ):
                    continue
                # Filter for CC-BY open access
                licenses = item.get("license", [])
                has_ccby = any(
                    "creativecommons.org/licenses/by" in (lic.get("URL", "") or "")
                    for lic in licenses
                )
                if not has_ccby:
                    continue
                doi = item.get("DOI")
                title = item.get("title", [""])[0] if item.get("title") else ""
                published = item.get("published-print", item.get("published-online", {}))
                year = published.get("date-parts", [[None]])[0][0] if published else None
                
                authors = []
                for author in item.get("author", []):
                    name = f"{author.get('given', '')} {author.get('family', '')}".strip()
                    if name:
                        authors.append(name)
                
                metas.append(PaperMeta(
                    source=self.name,
                    source_id=doi or "",
                    doi=doi,
                    title=title,
                    authors=authors,
                    published_at=datetime(year, 1, 1, tzinfo=timezone.utc) if year else None,
                    year=year,
                    landing_url=item.get("URL"),
                ))
            
            offset += len(items)
            time.sleep(self.rate_limit_delay)
            if len(items) < 100 or offset >= self.max_results:
                break
        return metas
    
    def download(self, meta: PaperMeta, dest_path: Path) -> Path:
        if not meta.doi:
            raise PaywalledError(f"No DOI for Wiley paper {meta.source_id}")
        url = WILEY_TDM.format(doi=meta.doi)
        headers = {"Wiley-TDM-Client-Token": self.tdm_token}
        
        resp = requests.get(url, headers=headers, allow_redirects=True, timeout=30)
        if resp.status_code == 403:
            raise PaywalledError(f"TDM 403: {meta.doi}")
        if resp.status_code == 200 and len(resp.content) > 10000:
            dest_path.write_bytes(resp.content)
            time.sleep(self.rate_limit_delay)
            return dest_path
        raise PaywalledError(f"Wiley download failed: {resp.status_code}")
