"""PoolClient Protocol and StubPoolClient placeholder."""
from __future__ import annotations

from typing import AsyncIterator, Protocol, runtime_checkable


@runtime_checkable
class PoolClient(Protocol):
    async def acquire(self, user_id: str, options_hash: int) -> str: ...
    def query(self, handle: str, prompt: str) -> AsyncIterator[dict]: ...
    async def release(self, handle: str, reusable: bool = True) -> None: ...
    async def interrupt(self, handle: str) -> None: ...


class StubPoolClient:
    """Placeholder pool client — replaced by real impl in follow-up PR."""

    async def acquire(self, user_id: str, options_hash: int) -> str:
        raise NotImplementedError("StubPoolClient: real pool not yet implemented")

    async def query(self, handle: str, prompt: str):
        raise NotImplementedError("StubPoolClient: real pool not yet implemented")
        # Make this an async generator by having an unreachable yield
        yield  # type: ignore[misc]

    async def release(self, handle: str, reusable: bool = True) -> None:
        raise NotImplementedError("StubPoolClient: real pool not yet implemented")

    async def interrupt(self, handle: str) -> None:
        raise NotImplementedError("StubPoolClient: real pool not yet implemented")
