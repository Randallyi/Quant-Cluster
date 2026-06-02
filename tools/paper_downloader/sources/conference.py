import requests
import time
import re
from datetime import datetime
from pathlib import Path
from typing import List
from sources.base import Source
from core.models import PaperMeta
from core.downloader import download_file, DownloadError


# Strict finance keywords — only papers explicitly about finance/quant are auto-downloaded.
# We use multi-word phrases to avoid false positives on generic terms.
_FINANCE_KWS = [
    # Core finance (high confidence)
    'finance', 'financial', 'trading', 'portfolio', 'asset pricing', 'stock market',
    'equity', 'bond', 'option', 'derivative', 'volatility', 'arbitrage',
    'investment', 'wealth management', 'credit risk', 'market risk',
    'foreign exchange', 'forex', 'exchange rate', 'econometric', 'quantitative',
    'monetary policy', 'hedge fund', 'mutual fund', 'dividend', 'yield',
    'momentum', 'factor model', 'market impact', 'liquidity',
    # Pricing contexts (must be explicit)
    'dynamic pricing', 'online pricing', 'auction', 'bidding',
    # Financial markets (must include "financial" or specific market type)
    'financial market', 'securities', 'commodity', 'futures',
    # Other explicit phrases
    'portfolio selection', 'optimal execution', 'algorithmic trading',
    'high-frequency trading', 'market making', 'order flow',
    'credit default', 'systemic risk', 'value at risk', 'var)',
]

# Single-word keywords that are too ambiguous alone — require finance context
_AMBIGUOUS_KWS = ['risk', 'price', 'market', 'economic', 'return', 'fund', 'pricing']


def _is_quant_relevant(title: str) -> bool:
    """Return True only if title explicitly mentions finance/quant keywords.
    
    NeurIPS is a general AI conference — pure ML/optimization/statistics
    papers are catalogued for agent review but NOT auto-downloaded.
    Agent can selectively download method papers if needed.
    """
    t = title.lower()
    
    # Explicit multi-word finance phrases → high confidence match
    if any(kw in t for kw in _FINANCE_KWS):
        return True
    
    # Ambiguous single words only count if combined with another finance term
    # (e.g., "Stock Price Prediction" has both "stock" and "price")
    has_ambiguous = any(kw in t for kw in _AMBIGUOUS_KWS)
    if has_ambiguous:
        finance_context = ['finance', 'financial', 'trading', 'portfolio', 'asset',
                           'stock', 'bond', 'option', 'derivative', 'investment',
                           'credit', 'market', 'economic', 'equity', 'quantitative']
        if any(kw in t for kw in finance_context):
            return True
    
    return False


class NeurIPSSource(Source):
    """NeurIPS proceedings scraper.
    
    All papers are scanned and saved to the database. Only papers with
    explicit finance/quant keywords are auto-downloaded; the rest are
    catalogued for agent review.
    """
    
    def __init__(self, year: int):
        self.year = year
        self.name = f"neurips_{year}"
        self.frequency = "yearly"
        self.rate_limit_delay = 2.0
        self.base_url = f"https://papers.nips.cc/paper/{year}"
    
    def should_auto_download(self, title: str) -> bool:
        """Return True if this paper should be auto-downloaded."""
        return _is_quant_relevant(title)
    
    def scan(self, since: datetime) -> List[PaperMeta]:
        metas = []
        resp = requests.get(self.base_url, timeout=30)
        resp.raise_for_status()
        # NeurIPS modern URL format extracts title and link directly from listing page
        seen = set()
        pattern = r'<a title="paper title" href="(/paper_files/paper/\d+/hash/[a-f0-9]+-[^"]+)">([^<]+)</a>'
        for match in re.finditer(pattern, resp.text):
            path = match.group(1)
            title = match.group(2).strip()
            if path in seen:
                continue
            seen.add(path)
            
            paper_url = f"https://papers.nips.cc{path}"
            # PDF URL: proceedings.neurips.cc uses /file/ instead of /hash/
            pdf_path = path.replace("/hash/", "/file/").replace("-Abstract-", "-Paper-").replace(".html", ".pdf")
            pdf_url = f"https://proceedings.neurips.cc{pdf_path}"
            
            metas.append(PaperMeta(
                source=self.name,
                source_id=path.split("/")[-1],
                title=title,
                year=self.year,
                pdf_url=pdf_url,
                landing_url=paper_url,
            ))
        return metas
    
    def download(self, meta: PaperMeta, dest_path: Path) -> Path:
        # Always reconstruct correct PDF URL — DB may contain old/wrong URLs
        if meta.landing_url:
            pdf_url = (
                meta.landing_url
                .replace("https://papers.nips.cc", "https://proceedings.neurips.cc")
                .replace("/hash/", "/file/")
                .replace("-Abstract-", "-Paper-")
                .replace(".html", ".pdf")
            )
        elif meta.pdf_url:
            pdf_url = (
                meta.pdf_url
                .replace("https://papers.nips.cc", "https://proceedings.neurips.cc")
                .replace("/hash/", "/file/")
            )
        else:
            raise DownloadError(f"No URL for NeurIPS paper {meta.source_id}")
        return download_file(pdf_url, dest_path, rate_limit_delay=self.rate_limit_delay)
