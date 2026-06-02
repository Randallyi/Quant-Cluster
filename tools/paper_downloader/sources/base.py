from abc import ABC, abstractmethod
from datetime import datetime
from pathlib import Path
from typing import List

from core.models import PaperMeta


class Source(ABC):
    name: str = ""
    frequency: str = ""  # "daily", "weekly", "monthly", "yearly", "on_demand"
    rate_limit_delay: float = 3.0
    max_retries: int = 3

    @abstractmethod
    def scan(self, since: datetime) -> List[PaperMeta]:
        ...

    @abstractmethod
    def download(self, meta: PaperMeta, dest_path: Path) -> Path:
        ...
