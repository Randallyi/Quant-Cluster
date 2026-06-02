"""AISTATS proceedings scraper — open access via PMLR."""

import requests
import re
from datetime import datetime
from pathlib import Path
from typing import List
from sources.base import Source
from core.models import PaperMeta
from core.downloader import download_file, DownloadError


# Re-use the same finance relevance filter from conference.py
_FINANCE_KWS = [
    'finance', 'financial', 'trading', 'portfolio', 'asset pricing', 'stock',
    'market', 'price', 'return', 'equity', 'bond', 'option', 'derivative',
    'risk', 'volatility', 'arbitrage', 'investment', 'wealth', 'credit',
    'economic', 'forex', 'exchange rate', 'econometric', 'quantitative',
    'monetary', 'fund', 'dividend', 'yield', 'momentum', 'factor',
    'market impact', 'liquidity', 'auction', 'bidding', 'pricing',
]

_QUANT_METHOD_KWS = [
    'forecasting', 'time series', 'time-series', 'causal inference',
    'bandit', 'regret bound', 'regret bounds', 'online convex',
    'online prediction', 'portfolio selection', 'dynamic pricing',
]


def _is_quant_relevant(title: str) -> bool:
    t = title.lower()
    has_finance = any(kw in t for kw in _FINANCE_KWS)
    has_method = any(kw in t for kw in _QUANT_METHOD_KWS)
    return has_finance or has_method


class AistatsSource(Source):
    """AISTATS proceedings scraper via PMLR.
    
    All papers are scanned and saved. Only quant-relevant papers are
    auto-downloaded; the rest are catalogued for agent review.
    """

    def __init__(self, year: int, volume: int):
        self.year = year
        self.volume = volume
        self.name = f"aistats_{year}"
        self.frequency = "yearly"
        self.rate_limit_delay = 1.0
        self.base_url = f"https://proceedings.mlr.press/v{volume}/"

    def should_auto_download(self, title: str) -> bool:
        return _is_quant_relevant(title)

    def scan(self, since: datetime) -> List[PaperMeta]:
        metas = []
        resp = requests.get(self.base_url, timeout=30)
        resp.raise_for_status()

        # Each paper is in a <div class="paper"> block
        paper_blocks = re.findall(
            r'<div class="paper">\s*<p class="title">([^<]+)</p>\s*'
            r'.*?href="(https://raw\.githubusercontent\.com/mlresearch/v\d+/main/assets/([^/]+)/[^"]+\.pdf)"',
            resp.text,
            re.DOTALL,
        )

        for title, pdf_url, paper_id in paper_blocks:
            title = title.strip()
            # Landing page URL
            landing_url = f"{self.base_url}{paper_id}.html"
            metas.append(PaperMeta(
                source=self.name,
                source_id=paper_id,
                title=title,
                year=self.year,
                pdf_url=pdf_url,
                landing_url=landing_url,
            ))

        return metas

    def download(self, meta: PaperMeta, dest_path: Path) -> Path:
        if not meta.pdf_url:
            raise DownloadError(f"No PDF URL for AISTATS paper {meta.source_id}")
        return download_file(meta.pdf_url, dest_path, rate_limit_delay=self.rate_limit_delay)
