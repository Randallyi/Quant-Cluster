from dataclasses import dataclass, asdict
from datetime import datetime
from pathlib import Path
from typing import List, Optional
import json
import re


@dataclass
class PaperMeta:
    """一篇论文的元数据，所有 Source 统一输出此格式"""
    source: str
    source_id: str
    doi: Optional[str] = None
    title: str = ""
    authors: Optional[List[str]] = None
    abstract: Optional[str] = None
    published_at: Optional[datetime] = None
    year: Optional[int] = None
    pdf_url: Optional[str] = None
    landing_url: Optional[str] = None

    def unique_key(self) -> str:
        """去重标识：有 DOI 用 DOI，否则用 source + source_id"""
        doi = self.doi.strip() if self.doi else None
        return doi.lower() if doi else f"{self.source}:{self.source_id}"

    def suggested_filename(self) -> str:
        """建议的文件名：{source}_{safe_id}.pdf"""
        safe_id = re.sub(r'[\\/:*?"<>|\x00]', "_", str(self.source_id))
        return f"{self.source}_{safe_id}.pdf"
