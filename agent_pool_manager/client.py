"""PoolClient — HTTP client for callers to interact with the agent pool service."""
from __future__ import annotations

import json
import logging
from typing import Any, AsyncIterator

import httpx

log = logging.getLogger(__name__)


class PoolClientError(Exception):
    """Raised when the pool service returns an error response."""


class PoolClient:
    """Thin HTTP wrapper around the agent-pool-manager service endpoints.

    All callers (interactive-agent-layer, bot pipelines) use this class
    rather than speaking to the service directly.  The pool service URL
    is configured via ``agent_pool.base_url`` in app_config.yaml.

    Parameters
    ----------
    base_url:
        Base URL of the pool service, e.g. ``http://agent-pool:5002``.
    _transport:
        Optional httpx transport override — used in tests to inject an
        in-process ASGI transport instead of making real TCP connections.
    """

    def __init__(
        self,
        base_url: str = "http://127.0.0.1:5002",
        *,
        _transport: httpx.AsyncBaseTransport | None = None,
    ) -> None:
        self._base_url = base_url.rstrip("/")
        self._transport = _transport
        self._client: httpx.AsyncClient | None = None

    def _get_client(self) -> httpx.AsyncClient:
        if self._client is None:
            self._client = httpx.AsyncClient(
                base_url=self._base_url,
                timeout=30.0,
                transport=self._transport,
            )
        return self._client

    async def aclose(self) -> None:
        """Close the underlying HTTP client."""
        if self._client is not None:
            await self._client.aclose()
            self._client = None

    async def __aenter__(self) -> "PoolClient":
        return self

    async def __aexit__(self, *args: Any) -> None:
        await self.aclose()

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    async def acquire(
        self,
        user_id: str,
        options_hash: str,
        options: dict[str, Any],
        timeout_seconds: float | None = None,
    ) -> str:
        """Acquire a warm subprocess handle.

        Returns the ``handle_id`` string.
        Raises :exc:`PoolClientError` if the pool is exhausted.
        """
        payload: dict[str, Any] = {
            "user_id": user_id,
            "options_hash": options_hash,
            "options": options,
        }
        if timeout_seconds is not None:
            payload["timeout_seconds"] = timeout_seconds

        resp = await self._get_client().post("/acquire", json=payload)

        if resp.status_code == 503:
            body = resp.json()
            raise PoolClientError(
                f"pool_exhausted — retry after {body.get('retry_after_seconds', 5)}s"
            )
        _raise_for_status(resp)
        return resp.json()["handle_id"]

    async def release(self, handle_id: str, *, reusable: bool = False) -> None:
        """Release a handle.

        ``reusable=True`` returns the subprocess to the warm queue.
        ``reusable=False`` (default) terminates it.
        """
        resp = await self._get_client().post(
            f"/handle/{handle_id}/release",
            json={"reusable": reusable},
        )
        _raise_for_status(resp)

    async def interrupt(self, handle_id: str) -> None:
        """Send an interrupt to the active subprocess."""
        resp = await self._get_client().post(f"/handle/{handle_id}/interrupt")
        _raise_for_status(resp)

    async def query_stream(
        self,
        handle_id: str,
        prompt: str,
        session_id: str = "default",
    ) -> AsyncIterator[dict[str, Any]]:
        """Stream SDK events from a running query as an async iterator of dicts.

        Yields one dict per SSE ``data:`` line (parsed JSON).
        Stops at the ``[DONE]`` sentinel or on connection close.
        Raises :exc:`PoolClientError` if the handle is not found.
        """
        async with self._get_client().stream(
            "POST",
            f"/handle/{handle_id}/query",
            json={"prompt": prompt, "session_id": session_id},
            timeout=None,  # streaming — no fixed timeout
        ) as resp:
            if resp.status_code == 404:
                raise PoolClientError(f"handle not found: {handle_id!r}")
            _raise_for_status(resp)
            async for line in resp.aiter_lines():
                if not line.startswith("data: "):
                    continue
                payload = line[len("data: "):]
                if payload == "[DONE]":
                    return
                try:
                    yield json.loads(payload)
                except json.JSONDecodeError:
                    log.warning("Unparseable SSE payload: %r", payload)

    async def hint(
        self,
        user_id: str,
        options_hash: str,
        options: dict[str, Any],
    ) -> None:
        """Signal that a subprocess will likely be needed soon (best-effort)."""
        resp = await self._get_client().post(
            "/hint",
            json={"user_id": user_id, "options_hash": options_hash, "options": options},
        )
        _raise_for_status(resp)

    async def status(self) -> dict[str, Any]:
        """Return current pool status (warm/active/warming counts)."""
        resp = await self._get_client().get("/status")
        _raise_for_status(resp)
        return resp.json()


# ---------------------------------------------------------------------------
# Helper
# ---------------------------------------------------------------------------

def _raise_for_status(resp: httpx.Response) -> None:
    """Raise PoolClientError for non-2xx responses, with readable message."""
    if resp.is_success:
        return
    try:
        detail = resp.json().get("detail") or resp.text
    except Exception:
        detail = resp.text
    raise PoolClientError(f"HTTP {resp.status_code}: {detail}")


def from_config(tether_config: object) -> "PoolClient":
    """Build a PoolClient from a TetherConfig instance."""
    try:
        base_url: str = tether_config.get("agent_pool", {}).get(  # type: ignore[attr-defined]
            "base_url", "http://127.0.0.1:5002"
        )
    except Exception:
        base_url = "http://127.0.0.1:5002"
    return PoolClient(base_url=base_url)
