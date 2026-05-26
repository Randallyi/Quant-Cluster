import logging
from typing import List, Optional

from models import Bar, FundamentalData

logger = logging.getLogger(__name__)


class AKShareLoader:
    """Placeholder for AKShare (China A-share) data loader."""

    name = "akshare"

    def fetch_historical(self, **kwargs) -> List[Bar]:
        raise NotImplementedError("AKShare loader not yet implemented")

    def fetch_fundamental(self, ticker: str) -> Optional[FundamentalData]:
        raise NotImplementedError("AKShare loader not yet implemented")

    def health(self) -> dict:
        return {
            "available": False,
            "latency_ms": 0,
            "message": "not configured",
        }
