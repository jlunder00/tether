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


# Type aliases for injected callables
CheckGrantFn = Callable[[str, str, str, str], Awaitable[bool]]
InsertGrantFn = Callable[[str, str, str, str], Awaitable[None]]
# (from_node_id, to_node_id) -> hop count | None
HopDistanceFn = Callable[[str, str], Awaitable[int | None]]
# path -> node_id | None
ResolveNodePathFn = Callable[[str], Awaitable[str | None]]


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

    Scope-gating callables (optional, injected; None = no scope enforcement):
        scope_source_node_id: anchor node for this conversation's scope.
        scope_radius: M hops from source — targets beyond this distance are gated.
        scope_mode: "tree_distance" (undirected shortest path, default) or
            "descendant_only" (reserved for future use; treated as tree_distance).
        hop_distance_fn(from_id, to_id) -> int | None
            Returns undirected tree distance; None means unrelated trees.
            Pre-bound to a DB connection in production wiring; mocked in tests.
        resolve_node_path_fn(path) -> str | None
            Resolves a slash-separated path to a node_id for scope checking.
            None return means path not found — treated as out-of-scope.
            When not provided, any paths in read_context args are out-of-scope.
    """

    def __init__(
        self,
        translation_table: TranslationTable,
        session: Any,       # Session — avoid circular import
        outbound_events: asyncio.Queue,
        auto_approve_user_actions: bool = False,
        check_grant_fn: CheckGrantFn | None = None,
        insert_grant_fn: InsertGrantFn | None = None,
        # Scope-gating params — all None means no scope enforcement
        scope_source_node_id: str | None = None,
        scope_radius: int | None = None,
        scope_mode: str = "tree_distance",
        hop_distance_fn: HopDistanceFn | None = None,
        resolve_node_path_fn: ResolveNodePathFn | None = None,
    ) -> None:
        self._table = translation_table
        self._session = session
        self._outbound_events = outbound_events
        self._auto_approve = auto_approve_user_actions
        self._check_grant_fn = check_grant_fn
        self._insert_grant_fn = insert_grant_fn
        self._scope_source_node_id = scope_source_node_id
        self._scope_radius = scope_radius
        self._scope_mode = scope_mode
        self._hop_distance_fn = hop_distance_fn
        self._resolve_node_path_fn = resolve_node_path_fn

    async def can_use_tool(
        self,
        tool_name: str,
        args: dict[str, Any],
        ctx: Any,  # ToolPermissionContext — ignored for now
    ) -> PermissionResultAllow | PermissionResultDeny:
        # Scope check for read_context runs before normal translation dispatch.
        # read_context is classified as "background" (auto-allow) in the translation
        # table, but must be gated when its targets exceed the conversation's scope
        # radius.  All three conditions must be set; if any is None, no gating.
        if (
            tool_name == "read_context"
            and self._scope_source_node_id is not None
            and self._scope_radius is not None
            and self._hop_distance_fn is not None
        ):
            return await self._check_read_context_scope(args)

        entry = self._table.lookup(tool_name)
        return await self._dispatch(tool_name, args, entry)

    async def _check_read_context_scope(
        self,
        args: dict[str, Any],
    ) -> PermissionResultAllow | PermissionResultDeny:
        """Check whether read_context targets are within the session's scope radius.

        Collects all target node_ids (from node_ids arg and resolved paths),
        checks each against the hop distance, and gates on the first offender.
        An unresolvable path (resolver returns None or no resolver provided)
        is treated as out-of-scope to prevent bypass via path arguments.
        """
        node_ids: list[str] = list(args.get("node_ids") or [])
        paths: list[str] = list(args.get("paths") or [])

        # Resolve paths to node_ids; unresolvable → None (sentinel for out-of-scope)
        for path in paths:
            if self._resolve_node_path_fn is not None:
                resolved = await self._resolve_node_path_fn(path)
            else:
                resolved = None  # no resolver → treat path as out-of-scope
            node_ids.append(resolved)  # type: ignore[arg-type]

        # No targets at all → root read, always allow
        if not node_ids:
            return PermissionResultAllow()

        # Find first offending target
        offender: str | None = None
        offender_label: str = ""
        for nid in node_ids:
            if nid is None:
                # Unresolvable path
                offender = None
                offender_label = "(unresolved path)"
                break
            distance = await self._hop_distance_fn(self._scope_source_node_id, nid)
            if distance is None or distance > self._scope_radius:
                offender = nid
                offender_label = nid
                break
        else:
            # All targets within scope
            return PermissionResultAllow()

        # Gate: emit permission_request and await user response
        return await self._emit_scope_permission_request(offender_label)

    async def _emit_scope_permission_request(
        self,
        target_label: str,
    ) -> PermissionResultAllow | PermissionResultDeny:
        """Emit a read_out_of_scope permission_request and await user decision."""
        request_id = str(uuid.uuid4())

        loop = asyncio.get_running_loop()
        future: asyncio.Future[bool] = loop.create_future()
        self._session.permission_pending[request_id] = future

        await self._outbound_events.put(
            {
                "type": "permission_request",
                "kind": "read_out_of_scope",
                "session_id": self._session.session_id,
                "request_id": request_id,
                "target": target_label,
                "reason_from_bot": None,
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
