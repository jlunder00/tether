"""Permission gate — can_use_tool callback for agent-pool-manager PoolClient.query."""
from __future__ import annotations

import asyncio
import dataclasses
import uuid
from collections.abc import Callable, Awaitable
from typing import Any

from interactive_agent_layer.config import get_permission_timeout
from interactive_agent_layer.translation import (
    BackgroundEntry,
    BackgroundHiddenEntry,
    ForgivingMap,
    PassthroughEntry,
    TranslationEntry,
    TranslationTable,
    UserActionEntry,
)


@dataclasses.dataclass
class PermissionResultAllow:
    pass


@dataclasses.dataclass
class PermissionResultDeny:
    reason: str = "denied"


class PermissionTimeoutError(Exception):
    """Raised by PermissionGate when the user does not respond within the timeout.

    Carries the ``request_id`` so the caller (session.py) can include it in
    the ``session_timeout`` WebSocket event.
    """

    def __init__(self, request_id: str) -> None:
        super().__init__(f"Permission request timed out: {request_id}")
        self.request_id = request_id


# Type aliases for injected grant functions
CheckGrantFn = Callable[[str, str, str, str], Awaitable[bool]]
InsertGrantFn = Callable[[str, str, str, str], Awaitable[None]]


class PermissionGate:
    """
    Builds a can_use_tool callback for a specific session.

    The callback signature matches the claude-agent-sdk CanUseTool protocol:
        async (tool_name: str, args: dict, ctx: Any) -> PermissionResultAllow | PermissionResultDeny

    ``outbound_events`` receives permission_request dicts when a user_action tool
    needs approval.  Callers (run_turn) drain this queue and yield the events on
    the SSE stream so they cross the process boundary to the API / dispatch layer.

    Grant functions (optional, injected for testability and DB-decoupling):
        check_grant_fn(user_id, conversation_id, target, kind) -> bool
            Returns True if a stored grant already covers this request; the gate
            auto-allows and skips the interactive permission_request flow.
        insert_grant_fn(user_id, conversation_id, target, kind) -> None
            Called after the user approves to persist the grant for the
            remainder of the conversation.
    """

    def __init__(
        self,
        translation_table: TranslationTable,
        session: Any,       # Session — avoid circular import
        outbound_events: asyncio.Queue,
        auto_approve_user_actions: bool = False,
        check_grant_fn: CheckGrantFn | None = None,
        insert_grant_fn: InsertGrantFn | None = None,
    ) -> None:
        self._table = translation_table
        self._session = session
        self._outbound_events = outbound_events
        self._auto_approve = auto_approve_user_actions
        self._check_grant_fn = check_grant_fn
        self._insert_grant_fn = insert_grant_fn

    async def can_use_tool(
        self,
        tool_name: str,
        args: dict[str, Any],
        ctx: Any,  # ToolPermissionContext — ignored for now
    ) -> PermissionResultAllow | PermissionResultDeny:
        entry = self._table.lookup(tool_name)
        return await self._dispatch(tool_name, args, entry)

    async def _dispatch(
        self,
        tool_name: str,
        args: dict[str, Any],
        entry: TranslationEntry,
    ) -> PermissionResultAllow | PermissionResultDeny:
        if isinstance(entry, (BackgroundEntry, BackgroundHiddenEntry, PassthroughEntry)):
            return PermissionResultAllow()

        # UserActionEntry path
        if self._auto_approve:
            return PermissionResultAllow()

        # Human-readable target derived from the permission_summary template.
        target = entry.permission_summary.format_map(ForgivingMap(args))
        kind = entry.kind
        conv_id: str = getattr(self._session, "conversation_id", None) or ""

        # Check existing per-conversation grant — skip the interactive flow if found.
        if self._check_grant_fn is not None:
            granted = await self._check_grant_fn(
                self._session.user_id, conv_id, target, kind
            )
            if granted:
                return PermissionResultAllow()

        # Emit permission_request on the outbound queue — run_turn drains this and
        # yields the event on the SSE stream so it crosses the process boundary to
        # dispatch / the API layer.  WSPublisher is intentionally not used here: it
        # only works within the same OS process.
        request_id = str(uuid.uuid4())

        loop = asyncio.get_running_loop()
        future: asyncio.Future[bool] = loop.create_future()
        self._session.permission_pending[request_id] = future

        await self._outbound_events.put(
            {
                "type": "permission_request",
                "session_id": self._session.session_id,
                "request_id": request_id,
                "kind": kind,
                "target": target,
                "reason_from_bot": None,
            }
        )

        try:
            approved = await asyncio.wait_for(
                asyncio.shield(future),
                timeout=get_permission_timeout(),
            )
        except asyncio.TimeoutError:
            # Raise instead of silently denying — session.py catches this,
            # emits a session_timeout event, and ends the turn cleanly.
            raise PermissionTimeoutError(request_id)
        finally:
            self._session.permission_pending.pop(request_id, None)

        if approved and self._insert_grant_fn is not None:
            await self._insert_grant_fn(
                self._session.user_id, conv_id, target, kind
            )

        return PermissionResultAllow() if approved else PermissionResultDeny()
