"""ControlBridge — forwards SDK permission callbacks over the SSE stream.

When a ClaudeSDKClient fires its ``can_use_tool`` callback the pool cannot
answer directly — the decision lives in the calling layer on the other side of
an HTTP connection.  ControlBridge bridges the gap:

1. Pool calls ``bridge.request(handle_id, subtype, payload)`` — registers a
   Future keyed by a fresh ``request_id`` and returns the awaitable.
2. The SSE stream emits a ``control_request`` event carrying ``request_id``.
3. The layer calls ``POST /handle/{id}/control_response`` with the decision.
4. Server calls ``bridge.respond(request_id, payload)`` — resolves the Future.
5. ``request()`` unblocks and returns the response dict.

If no response arrives within ``timeout_seconds``, ``request()`` raises
:exc:`ControlTimeout` so the callback can return a deny result immediately.
"""
from __future__ import annotations

import asyncio
import logging
import uuid
from typing import Any

log = logging.getLogger(__name__)


class ControlTimeout(Exception):
    """Raised when no control_response arrives within the allowed window."""


class ControlBridge:
    """Manages in-flight permission-gate requests for one pool service instance.

    Each pending request is a ``Future`` keyed by a UUID ``request_id``.
    The bridge is shared across all active handles; ``handle_id`` is carried
    in the payload for traceability and routes SSE events to the right stream.

    **SSE integration** — ``register_handle()`` must be called before a query
    stream starts.  ``request()`` then puts a ``control_request`` dict into the
    handle's queue so the stream can emit it while the callback awaits the
    response.  Call ``deregister_handle()`` when the stream ends.

    Parameters
    ----------
    timeout_seconds:
        How long ``request()`` waits before raising :exc:`ControlTimeout`.
        Default matches ``agent_pool.control_response_timeout_seconds`` config.
    """

    def __init__(self, timeout_seconds: float = 60.0) -> None:
        self.timeout_seconds = timeout_seconds
        # request_id → Future[dict]
        self._pending: dict[str, asyncio.Future[dict[str, Any]]] = {}
        # per-handle SSE event queues — populated by request(), drained by stream
        self._handle_queues: dict[str, asyncio.Queue[dict[str, Any]]] = {}

    # ------------------------------------------------------------------
    # Handle queue management (called by server around each query stream)
    # ------------------------------------------------------------------

    def register_handle(self, handle_id: str) -> "asyncio.Queue[dict[str, Any]]":
        """Create and return an event queue for the given handle.

        The returned queue will receive ``control_request`` (and
        ``control_timeout``) dicts whenever the SDK fires ``can_use_tool``
        during a query.  The caller is responsible for draining the queue
        while simultaneously iterating the SDK response stream.
        """
        q: asyncio.Queue[dict[str, Any]] = asyncio.Queue()
        self._handle_queues[handle_id] = q
        return q

    def deregister_handle(self, handle_id: str) -> None:
        """Remove the event queue for the given handle (called when stream ends)."""
        self._handle_queues.pop(handle_id, None)

    # ------------------------------------------------------------------
    # Core protocol
    # ------------------------------------------------------------------

    async def request(
        self,
        handle_id: str,
        subtype: str,
        payload: dict[str, Any],
    ) -> dict[str, Any]:
        """Register a pending control request and await its resolution.

        Enqueues a ``control_request`` event in the handle's SSE queue (if
        registered) so the stream can emit it while this coroutine waits.

        Returns the response dict passed to :meth:`respond`.
        Raises :exc:`ControlTimeout` if no response arrives in time.
        """
        request_id = str(uuid.uuid4())
        fut: asyncio.Future[dict[str, Any]] = asyncio.get_running_loop().create_future()
        self._pending[request_id] = fut

        # Notify the handle's SSE stream immediately (non-blocking).
        q = self._handle_queues.get(handle_id)
        if q is not None:
            q.put_nowait({
                "event": "control_request",
                "request_id": request_id,
                "subtype": subtype,
                **payload,
            })

        log.debug(
            "control_request registered request_id=%s handle=%s subtype=%s",
            request_id, handle_id, subtype,
        )

        try:
            return await asyncio.wait_for(
                asyncio.shield(fut), timeout=self.timeout_seconds
            )
        except asyncio.TimeoutError:
            log.warning(
                "control_request timed out request_id=%s handle=%s",
                request_id, handle_id,
            )
            if q is not None:
                q.put_nowait({"event": "control_timeout", "request_id": request_id})
            raise ControlTimeout(
                f"No control_response for request_id={request_id!r} within "
                f"{self.timeout_seconds}s"
            )
        finally:
            self._pending.pop(request_id, None)

    def respond(self, request_id: str, payload: dict[str, Any]) -> bool:
        """Resolve a pending request with the given response payload.

        Returns ``True`` if the request was found and resolved, ``False`` if
        the ``request_id`` is unknown or already timed out / resolved.

        Parameters
        ----------
        request_id:
            The ``request_id`` from the original ``control_request`` SSE event.
        payload:
            Decision payload, e.g. ``{"decision": "allow"}`` or
            ``{"decision": "deny", "denial_message": "..."}``.
        """
        fut = self._pending.get(request_id)
        if fut is None or fut.done():
            return False
        fut.set_result(payload)
        log.debug("control_response resolved request_id=%s", request_id)
        return True
