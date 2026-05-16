"""Async Hermes Agent client — wraps OpenAI-compatible chat API."""
import asyncio
from typing import AsyncIterator, Optional

import httpx
from openai import AsyncOpenAI


class AsyncHermesClient:
    """Async client for a single Hermes Agent container."""

    def __init__(self, port: int, api_key: str, model: str = "hermes-agent"):
        self.port = port
        self.model = model
        self._client = AsyncOpenAI(
            base_url=f"http://localhost:{port}/v1",
            api_key=api_key,
        )
        self._http = httpx.AsyncClient(timeout=httpx.Timeout(600.0, connect=10.0))

    # ------------------------------------------------------------------
    # Core chat
    # ------------------------------------------------------------------
    async def chat(
        self,
        system_prompt: str,
        user_prompt: str,
        timeout: float = 600.0,
    ) -> str:
        """Blocking chat call. Returns full text response."""
        response = await self._client.chat.completions.create(
            model=self.model,
            messages=[
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": user_prompt},
            ],
            timeout=timeout,
        )
        return response.choices[0].message.content or ""

    async def chat_stream(
        self,
        system_prompt: str,
        user_prompt: str,
        timeout: float = 600.0,
    ) -> AsyncIterator[str]:
        """Streaming chat call. Yields text chunks as they arrive."""
        stream = await self._client.chat.completions.create(
            model=self.model,
            messages=[
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": user_prompt},
            ],
            stream=True,
            timeout=timeout,
        )
        async for chunk in stream:
            if not chunk.choices:
                continue
            choice = chunk.choices[0]
            if not choice.delta or not choice.delta.content:
                continue
            yield choice.delta.content

    # ------------------------------------------------------------------
    # Health & utilities
    # ------------------------------------------------------------------
    async def health_check(self) -> bool:
        try:
            r = await self._http.get(f"http://localhost:{self.port}/health", timeout=5.0)
            return r.status_code == 200
        except Exception:
            return False

    async def close(self):
        await self._http.aclose()
