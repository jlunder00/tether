"""Fake ClaudeSDKClient for unit tests — no real subprocess spawned."""
from __future__ import annotations

import asyncio
from typing import AsyncIterator, Any
from unittest.mock import AsyncMock

from claude_agent_sdk import ResultMessage


def _make_result() -> ResultMessage:
    return ResultMessage(
        subtype="success",
        duration_ms=10,
        duration_api_ms=5,
        is_error=False,
        num_turns=1,
        session_id="fake-session",
        result="ready",
    )


class FakeClient:
    """Drop-in async fake for ClaudeSDKClient."""

    def __init__(self, options: Any = None, *, fail_connect: bool = False):
        self.options = options
        self.fail_connect = fail_connect
        self.connected = False
        self.disconnected = False
        self.queries: list[str] = []
        self.interrupted = False
        # simulate priming delay (none by default)
        self.connect_delay: float = 0.0
        # events stream to yield on receive_response (default: one ResultMessage)
        self._response_messages: list = [_make_result()]

    async def connect(self, prompt: Any = None) -> None:
        if self.connect_delay:
            await asyncio.sleep(self.connect_delay)
        if self.fail_connect:
            raise RuntimeError("connect failed")
        self.connected = True

    async def disconnect(self) -> None:
        self.disconnected = True

    async def query(self, prompt: Any, session_id: str = "default") -> None:
        self.queries.append(str(prompt))

    async def interrupt(self) -> None:
        self.interrupted = True

    async def receive_response(self) -> AsyncIterator:
        for msg in self._response_messages:
            yield msg

    async def __aenter__(self) -> "FakeClient":
        await self.connect()
        return self

    async def __aexit__(self, *args: Any) -> bool:
        await self.disconnect()
        return False
