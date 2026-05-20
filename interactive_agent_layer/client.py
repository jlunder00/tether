"""LayerClient — httpx-based client for bot pipelines to call the layer HTTP API."""
from __future__ import annotations

import json
from typing import AsyncIterator

import httpx


class LayerClient:
    """HTTP client for the interactive agent layer service."""

    def __init__(self, base_url: str) -> None:
        self.base_url = base_url.rstrip("/")
        self._client: httpx.AsyncClient | None = None

    def _get_client(self) -> httpx.AsyncClient:
        if self._client is not None:
            return self._client
        return httpx.AsyncClient(base_url=self.base_url)

    async def start_session(
        self,
        user_id: str,
        user_ws_id: str,
        agent_version: str,
        options: dict,
        user_message: str,
    ) -> str:
        """Returns session_id string."""
        client = self._get_client()
        resp = await client.post(
            f"{self.base_url}/session/start",
            json={
                "user_id": user_id,
                "user_ws_id": user_ws_id,
                "agent_version": agent_version,
                "options": options,
                "user_message": user_message,
            },
        )
        resp.raise_for_status()
        return resp.json()["session_id"]

    async def end_session(self, session_id: str) -> None:
        client = self._get_client()
        resp = await client.post(f"{self.base_url}/session/{session_id}/end")
        resp.raise_for_status()

    async def interrupt(self, session_id: str) -> None:
        client = self._get_client()
        resp = await client.post(f"{self.base_url}/session/{session_id}/interrupt")
        resp.raise_for_status()

    async def get_status(self, session_id: str) -> dict:
        client = self._get_client()
        resp = await client.get(f"{self.base_url}/session/{session_id}/status")
        resp.raise_for_status()
        return resp.json()

    async def turn(self, session_id: str, prompt: str) -> AsyncIterator[dict]:
        """Stream SSE events from the layer. Yields parsed dicts."""
        client = self._get_client()
        async with client.stream(
            "POST",
            f"{self.base_url}/session/{session_id}/turn",
            json={"prompt": prompt},
        ) as resp:
            resp.raise_for_status()
            buffer = ""
            async for chunk in resp.aiter_text():
                buffer += chunk
            for block in buffer.split("\n\n"):
                block = block.strip()
                if not block:
                    continue
                for line in block.splitlines():
                    if line.startswith("data: "):
                        yield json.loads(line[6:])
