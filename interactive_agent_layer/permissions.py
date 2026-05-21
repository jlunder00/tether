"""Permission gate — can_use_tool callback for agent-pool-manager PoolClient.query."""
from __future__ import annotations

import asyncio
import dataclasses
import uuid
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


class PermissionGate:
    """
    Builds a can_use_tool callback for a specific session.

    The callback signature matches the claude-agent-sdk CanUseTool protocol:
        async (tool_name: str, args: dict, ctx: Any) -> PermissionResultAllow | PermissionResultDeny

    ``outbound_events`` receives permission_request dicts when a user_action tool
    needs approval.  Callers (run_turn) drain this queue and yield the events on
    the SSE stream so they cross the process boundary to the API / dispatch layer.
    """

    def __init__(
        self,
        translation_table: TranslationTable,
        session: Any,       # Session — avoid circular import
        outbound_events: asyncio.Queue,
        auto_approve_user_actions: bool = False,
    ) -> None:
        self._table = translation_table
        self._session = session
        self._outbound_events = outbound_events
        self._auto_approve = auto_approve_user_actions

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

        # Emit permission_request, await user response
        request_id = str(uuid.uuid4())
        detail = args.get(entry.permission_detail_field, [])
        summary = entry.permission_summary.format_map(ForgivingMap(args))

        loop = asyncio.get_running_loop()
        future: asyncio.Future[bool] = loop.create_future()
        self._session.permission_pending[request_id] = future

        # Emit on the outbound queue — run_turn drains this and yields the
        # event on the SSE stream so it crosses the process boundary to
        # dispatch / the API layer.  WSPublisher is intentionally not used
        # here: it only works within the same OS process.
        await self._outbound_events.put(
            {
                "type": "permission_request",
                "session_id": self._session.session_id,
                "request_id": request_id,
                "summary": summary,
                "details": detail,
            }
        )

        try:
            approved = await asyncio.wait_for(
                asyncio.shield(future),
                timeout=get_permission_timeout(),
            )
        except asyncio.TimeoutError:
            approved = False
        finally:
            self._session.permission_pending.pop(request_id, None)

        return PermissionResultAllow() if approved else PermissionResultDeny()
