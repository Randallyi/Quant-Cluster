"""FastAPI dependencies for the data router."""

from fastapi import Request

from cache.manager import CacheManager
from ibkr.client import IBKRClient


def get_ibkr_client(request: Request) -> IBKRClient:
    """Return the shared IBKRClient instance attached to app state."""
    return request.app.state.ibkr_client


def get_cache_manager(request: Request) -> CacheManager:
    """Return the shared CacheManager instance attached to app state."""
    return request.app.state.cache
