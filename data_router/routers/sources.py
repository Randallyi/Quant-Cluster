"""Data source health and availability endpoint."""

import logging
from typing import Optional

from fastapi import APIRouter

from cache.manager import CacheManager
from ibkr.client import IBKRClient
from ibkr.connection_pool import ClientIdPool
from loaders.akshare_loader import AKShareLoader
from loaders.yfinance_loader import YFinanceLoader
from models import DataResponse, SourceHealth

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/sources", tags=["sources"])

_ibkr_client: Optional[IBKRClient] = None
_cache = CacheManager()
_yf_loader = YFinanceLoader()


def _get_ibkr_client() -> Optional[IBKRClient]:
    """Lazy init IBKR client for health checks (clientId 110 to avoid conflict with main app)."""
    global _ibkr_client
    if _ibkr_client is None:
        import os

        host = os.getenv("TWS_HOST", "host.docker.internal")
        port = int(os.getenv("TWS_PORT", "7497"))
        _ibkr_client = IBKRClient(host=host, port=port)
        _ibkr_client._main_client_id = 110
        _ibkr_client.pool = ClientIdPool(start=110, end=119)
        _ibkr_client.connect()
    return _ibkr_client


@router.get("", response_model=DataResponse)
async def list_sources():
    request_id = "sources-" + str(hash(str(_cache.stats())))[:8]

    sources: list[SourceHealth] = []
    cache_stats = _cache.stats()

    # IBKR
    ibkr_client = _get_ibkr_client()
    ibkr_health = ibkr_client.health() if ibkr_client else {"connected": False}
    ibkr_cache = cache_stats.get("sources", {}).get("ibkr", {})
    sources.append(
        SourceHealth(
            name="ibkr",
            available=ibkr_health.get("connected", False),
            markets=["US", "HK", "JP", "EU"],
            latency_ms=ibkr_health.get("latency_ms"),
            message="connected" if ibkr_health.get("connected") else "disconnected",
            cache_stats=ibkr_cache,
        )
    )

    # YFinance
    yf_health = _yf_loader.health()
    yf_cache = cache_stats.get("sources", {}).get("yfinance", {})
    sources.append(
        SourceHealth(
            name="yfinance",
            available=yf_health.get("available", False),
            markets=["US", "HK"],
            latency_ms=yf_health.get("latency_ms"),
            message=yf_health.get("message", ""),
            cache_stats=yf_cache,
        )
    )

    # AKShare (placeholder)
    ak_loader = AKShareLoader()
    ak_health = ak_loader.health()
    sources.append(
        SourceHealth(
            name="akshare",
            available=False,
            markets=["CN"],
            latency_ms=None,
            message="not configured",
            cache_stats={},
        )
    )

    return DataResponse(
        status="success",
        source="data_router",
        request_id=request_id,
        data=[s.model_dump() for s in sources],
        metadata={
            "total_sources": len(sources),
            "available": sum(1 for s in sources if s.available),
        },
        cached=False,
        fetch_time_ms=0,
    )
