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

    @property
    def client(self) -> httpx.AsyncClient:
        if self._client is None:
            self._client = httpx.AsyncClient(base_url=self.base_url)
        return self._client

    async def start_session(
        self,
        user_id: str,
        user_ws_id: str,
        agent_version: str,
        options: dict,
        user_message: str,
        conversation_id: str | None = None,
    ) -> str:
        """Returns session_id string.

        conversation_id is optional — when provided it links the session to
        a conversation so the layer can resolve scope_source_node_id from the
        conversation's context_node_id (scope gating). Omitting it is fully
        backwards-compatible.
        """
        resp = await self.client.post(
            f"{self.base_url}/session/start",
            json={
                "user_id": user_id,
                "user_ws_id": user_ws_id,
                "agent_version": agent_version,
                "options": options,
                "user_message": user_message,
                "conversation_id": conversation_id,
            },
        )
        resp.raise_for_status()
        return resp.json()["session_id"]

    async def end_session(self, session_id: str) -> None:
        resp = await self.client.post(f"{self.base_url}/session/{session_id}/end")
        resp.raise_for_status()

    async def interrupt(self, session_id: str) -> None:
        resp = await self.client.post(f"{self.base_url}/session/{session_id}/interrupt")
        resp.raise_for_status()

    async def get_status(self, session_id: str) -> dict:
        resp = await self.client.get(f"{self.base_url}/session/{session_id}/status")
        resp.raise_for_status()
        return resp.json()

    async def turn(self, session_id: str, prompt: str) -> AsyncIterator[dict]:
        """Stream SSE events from the layer. Yields parsed dicts incrementally.

        Events are yielded as complete SSE blocks arrive — no full-response
        buffering. Incomplete blocks are held in the buffer until the next
        chunk completes them or the stream closes.
        """
        async with self.client.stream(
            "POST",
            f"{self.base_url}/session/{session_id}/turn",
            json={"prompt": prompt},
        ) as resp:
            resp.raise_for_status()
            buffer = ""
            async for chunk in resp.aiter_text():
                buffer += chunk
                # Drain all complete SSE blocks (separated by blank lines).
                while "\n\n" in buffer:
                    block, buffer = buffer.split("\n\n", 1)
                    for line in block.splitlines():
                        if line.startswith("data: "):
                            yield json.loads(line[6:])
            # Flush any trailing block not terminated by a blank line.
            if buffer.strip():
                for line in buffer.splitlines():
                    if line.startswith("data: "):
                        yield json.loads(line[6:])
