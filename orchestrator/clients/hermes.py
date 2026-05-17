"""Async Hermes Agent client — wraps OpenAI-compatible chat API."""
import json
from typing import AsyncIterator, Optional

import aiohttp


class AsyncHermesClient:
    """Async client for a single Hermes Agent container."""

    def __init__(self, port: int, api_key: str, model: str = "hermes-agent"):
        self.port = port
        self.model = model
        self.api_key = api_key
        self._http_session: Optional[aiohttp.ClientSession] = None

    def _get_session(self) -> aiohttp.ClientSession:
        if self._http_session is None or self._http_session.closed:
            self._http_session = aiohttp.ClientSession(
                timeout=aiohttp.ClientTimeout(total=1800, connect=10)
            )
        return self._http_session

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
        session = self._get_session()
        url = f"http://localhost:{self.port}/v1/chat/completions"
        payload = {
            "model": self.model,
            "messages": [
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": user_prompt},
            ],
        }
        headers = {
            "Authorization": f"Bearer {self.api_key}",
            "Content-Type": "application/json",
        }
        async with session.post(url, json=payload, headers=headers) as resp:
            resp.raise_for_status()
            data = await resp.json()
            return data["choices"][0]["message"]["content"] or ""

    async def chat_stream(
        self,
        system_prompt: str,
        user_prompt: str,
        timeout: float = 1800.0,
    ) -> AsyncIterator[str]:
        """Streaming chat call. Yields text chunks as they arrive."""
        session = self._get_session()
        url = f"http://localhost:{self.port}/v1/chat/completions"
        payload = {
            "model": self.model,
            "messages": [
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": user_prompt},
            ],
            "stream": True,
        }
        headers = {
            "Authorization": f"Bearer {self.api_key}",
            "Content-Type": "application/json",
            "Accept": "text/event-stream",
        }
        async with session.post(url, json=payload, headers=headers) as resp:
            resp.raise_for_status()
            async for line in resp.content:
                line = line.decode("utf-8").strip()
                if line.startswith("data: "):
                    data_str = line[6:]
                    if data_str == "[DONE]":
                        break
                    try:
                        chunk = json.loads(data_str)
                    except json.JSONDecodeError:
                        continue
                    if not chunk.get("choices"):
                        continue
                    choice = chunk["choices"][0]
                    delta = choice.get("delta", {})
                    content = delta.get("content")
                    if content:
                        yield content

    # ------------------------------------------------------------------
    # Health & utilities
    # ------------------------------------------------------------------
    async def health_check(self) -> bool:
        session = self._get_session()
        try:
            async with session.get(
                f"http://localhost:{self.port}/health",
                timeout=aiohttp.ClientTimeout(total=5),
            ) as resp:
                return resp.status == 200
        except Exception:
            return False

    async def close(self):
        if self._http_session and not self._http_session.closed:
            await self._http_session.close()
