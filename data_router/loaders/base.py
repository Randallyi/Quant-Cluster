from typing import Protocol, List, Optional

from models import Bar, FundamentalData


class LoaderProtocol(Protocol):
    """Protocol for data loaders. Implementations are not required to inherit."""

    name: str

    def fetch_historical(self, **kwargs) -> List[Bar]:
        """Fetch historical bars. Return standardized Bar list."""
        ...

    def fetch_fundamental(self, ticker: str) -> Optional[FundamentalData]:
        """Fetch fundamental data. Return None if not supported."""
        ...

    def health(self) -> dict:
        """Return health status: {available: bool, latency_ms: int, message: str}"""
        ...
