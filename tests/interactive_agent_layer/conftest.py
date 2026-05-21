"""Fixtures for interactive_agent_layer tests."""
from __future__ import annotations

import pytest
from httpx import AsyncClient, ASGITransport

from interactive_agent_layer.ws_publisher import WSPublisher
from interactive_agent_layer.session import Layer


class MockPoolClient:
    """Fake pool: immediately returns a handle and yields hardcoded SDK events."""

    async def acquire(self, user_id: str, options_hash: int) -> str:
        return f"mock-handle-{user_id}"

    async def query(self, handle: str, prompt: str):
        yield {"type": "text_delta", "delta": "Hello "}
        yield {"type": "text_delta", "delta": "world"}
        yield {"type": "result", "final_text": "Hello world", "tokens_used": 42}

    async def release(self, handle: str, reusable: bool = True) -> None:
        pass

    async def interrupt(self, handle: str) -> None:
        pass


@pytest.fixture
def mock_pool_client():
    return MockPoolClient()


@pytest.fixture
def ws_publisher():
    return WSPublisher()


@pytest.fixture
def layer(mock_pool_client, ws_publisher):
    return Layer(pool_client=mock_pool_client, ws_publisher=ws_publisher)


@pytest.fixture
async def layer_client(layer):
    """AsyncClient with ASGITransport wired to the FastAPI app."""
    from interactive_agent_layer.server import create_app

    app = create_app(layer)
    async with AsyncClient(
        transport=ASGITransport(app=app),
        base_url="http://test",
    ) as client:
        yield client
