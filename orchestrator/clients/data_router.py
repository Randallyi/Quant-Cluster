"""Async client for the data_router service."""
from typing import Any, Dict

import httpx


class DataRouterClient:
    """REST client for data_router:8888."""

    def __init__(self, base_url: str = "http://localhost:8888"):
        self.base_url = base_url.rstrip("/")
        self._client = httpx.AsyncClient(
            base_url=self.base_url,
            timeout=httpx.Timeout(60.0, connect=5.0),
        )

    async def health(self) -> Dict[str, Any]:
        r = await self._client.get("/health")
        r.raise_for_status()
        return r.json()

    async def get_historical_data(self, request: Dict[str, Any]) -> Dict[str, Any]:
        r = await self._client.post("/data/historical", json=request)
        r.raise_for_status()
        return r.json()

    async def close(self):
        await self._client.aclose()
