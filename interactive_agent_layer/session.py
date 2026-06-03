"""Session dataclass and Layer class."""
from __future__ import annotations

import asyncio
import contextlib
import dataclasses
import hashlib
import json
import logging
import time
import uuid
from collections.abc import Callable
from typing import AsyncIterator, Any

from interactive_agent_layer.coalescing import CoalescingBuffer
from interactive_agent_layer.config import get_auto_approve_user_actions
from interactive_agent_layer.permissions import (
    PermissionGate,
    PermissionResultAllow,
)
from interactive_agent_layer.pool_client import PoolClient, PoolClientError
from interactive_agent_layer.translation import (
    BackgroundEntry,
    BackgroundHiddenEntry,
    PassthroughEntry,
    TranslationTable,
    UserActionEntry,
)
from interactive_agent_layer.ws_publisher import WSPublisher

log = logging.getLogger(__name__)


@dataclasses.dataclass
class Session:
    session_id: str
    user_id: str
    user_ws_id: str
    agent_version: str
    options: dict
    active_handles: list = dataclasses.field(default_factory=list)
    turn_count: int = 0
    created_at: float = dataclasses.field(default_factory=time.time)
    permission_pending: dict = dataclasses.field(default_factory=dict)
    coalescing_buffer: CoalescingBuffer = dataclasses.field(default_factory=CoalescingBuffer)
    # Optional: linked conversation for per-conversation permission grants.
    conversation_id: str | None = None
    # Tracks the last emitted agent_action so we can synthesize a 'complete'
    # status when the next distinct tool_use or turn_complete arrives.
    last_emitted_action: dict | None = None


def _stable_options_hash(options: dict) -> str:
    """Return a stable, process-safe string hash of options.

    Uses SHA-256 of the canonical JSON so the hash is consistent across
    processes and restarts (unlike Python's built-in hash() which is
    randomised via PYTHONHASHSEED).
    """
    canonical = json.dumps(options, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(canonical.encode()).hexdigest()[:16]


class Layer:
    def __init__(
        self,
        pool_client: PoolClient,
        ws_publisher: WSPublisher,
        translation_table: TranslationTable | None = None,
        *,
        trial_counter: Any = None,
        is_paid_fn: Callable[..., Any] | None = None,
        provider_fn: Callable[[str], str] | None = None,
        leaky_providers: list[str] | None = None,
    ) -> None:
        self.sessions: dict[str, Session] = {}
        self.pool_client = pool_client
        self.ws_publisher = ws_publisher
        self.translation_table = translation_table or TranslationTable.from_yaml()
        # Gate dependencies — None means no gate enforcement
        self.trial_counter = trial_counter
        self.is_paid_fn = is_paid_fn
        self.provider_fn = provider_fn
        self.leaky_providers = leaky_providers

    def create_session(
        self,
        user_id: str,
        user_ws_id: str,
        agent_version: str,
        options: dict,
        *,
        conversation_id: str | None = None,
    ) -> Session:
        session_id = str(uuid.uuid4())
        session = Session(
            session_id=session_id,
            user_id=user_id,
            user_ws_id=user_ws_id,
            agent_version=agent_version,
            options=options,
            conversation_id=conversation_id,
        )
        self.sessions[session_id] = session
        return session

    def get_session(self, session_id: str) -> Session | None:
        return self.sessions.get(session_id)

    def end_session(self, session_id: str) -> None:
        self.sessions.pop(session_id, None)

    async def run_turn(self, session_id: str, prompt: str) -> AsyncIterator[dict]:
        session = self.sessions[session_id]  # raises KeyError if missing
        options_hash = _stable_options_hash(session.options)

        # PermissionGate routes pool control_request SSE events through policy:
        # background/passthrough → auto-allow; user_action → prompt user or
        # auto-approve based on config.  Decisions are forwarded back to the
        # pool via send_control_response, which unblocks the pool's can_use_tool
        # callback and lets the SDK proceed or skip the tool call.
        #
        # permission_request events are enqueued here and yielded on the SSE
        # stream so they cross the process boundary to the dispatch / API layer.
        # WSPublisher (in-process only) is not used for permission_request.
        gate_events: asyncio.Queue[dict] = asyncio.Queue()
        gate = PermissionGate(
            translation_table=self.translation_table,
            session=session,
            outbound_events=gate_events,
            auto_approve_user_actions=get_auto_approve_user_actions(),
        )

        handle = await self.pool_client.acquire(
            session.user_id, options_hash, session.options
        )
        session.active_handles.append(handle)
        try:
            async for sdk_event in self.pool_client.query_stream(
                handle, prompt, session_id=session_id
            ):
                # Pool blocks its can_use_tool callback until we respond —
                # process control events inline before translating other events.
                if sdk_event.get("event") == "control_request":
                    ctrl_task = asyncio.create_task(
                        _handle_control_request(sdk_event, handle, gate, self.pool_client)
                    )
                    # Drain gate_events while the permission decision is pending.
                    # For background/passthrough tools ctrl_task completes immediately
                    # and the drain loop exits without yielding anything.
                    # For user_action tools a permission_request event is put into
                    # gate_events; we yield it on the SSE stream so dispatch's
                    # event_fn can forward it to the user's WebSocket.
                    async for gate_event in _drain_until_done(gate_events, ctrl_task):
                        yield gate_event
                    await ctrl_task  # propagate any exception
                    continue

                if sdk_event.get("event") == "control_timeout":
                    # Pool already denied the tool call; nothing to do.
                    continue

                async for layer_event in _translate_event(
                    session_id, sdk_event, self.translation_table, session
                ):
                    await self.ws_publisher.push(session.user_ws_id, layer_event)
                    yield layer_event
        finally:
            if handle in session.active_handles:
                session.active_handles.remove(handle)
            await self.pool_client.release(handle, reusable=True)
            session.turn_count += 1

    async def interrupt(self, session_id: str) -> None:
        session = self.sessions.get(session_id)
        if session is None:
            return
        for handle in list(session.active_handles):
            await self.pool_client.interrupt(handle)


async def _handle_control_request(
    event: dict,
    handle_id: str,
    gate: PermissionGate,
    pool_client: PoolClient,
) -> None:
    """Route a pool control_request through PermissionGate and send the decision back.

    If the pool already timed out and resolved the request before we respond,
    send_control_response returns 404 — we swallow that specific error so the
    turn can complete normally.
    """
    tool_name = event.get("tool_name", "")
    tool_input = event.get("tool_input", {})
    request_id = event.get("request_id", "")
    subtype = event.get("subtype", "can_use_tool")

    result = await gate.can_use_tool(tool_name, tool_input, None)
    decision = "allow" if isinstance(result, PermissionResultAllow) else "deny"
    denial_message = getattr(result, "reason", None) if decision == "deny" else None

    try:
        await pool_client.send_control_response(
            handle_id,
            request_id=request_id,
            subtype=subtype,
            decision=decision,
            denial_message=denial_message,
        )
    except PoolClientError as exc:
        # 404 means pool already timed out and denied this request — safe to ignore.
        log.debug(
            "send_control_response ignored (pool already resolved): %s request_id=%s",
            exc,
            request_id,
        )


async def _drain_until_done(
    queue: asyncio.Queue,
    task: asyncio.Task,
) -> AsyncIterator[dict]:
    """Yield items from queue until task is done.

    Uses asyncio.wait to race a queue.get() against the task completing so
    we exit promptly without polling.  The get_task is cancelled on exit to
    avoid leaving orphaned tasks.
    """
    while not task.done():
        get_task: asyncio.Task = asyncio.ensure_future(queue.get())
        try:
            done, _ = await asyncio.wait(
                [get_task, task],
                return_when=asyncio.FIRST_COMPLETED,
            )
        except BaseException:
            get_task.cancel()
            with contextlib.suppress(asyncio.CancelledError):
                await get_task
            raise
        if get_task in done:
            yield get_task.result()
        else:
            # task completed before a queue item arrived — clean up and exit
            get_task.cancel()
            with contextlib.suppress(asyncio.CancelledError):
                await get_task


async def _translate_event(
    session_id: str,
    sdk_event: dict,
    table: TranslationTable,
    session: Session,
) -> AsyncIterator[dict]:
    """Translate a raw SDK event to one or more layer events.

    agent_action lifecycle (heuristic — no tool_result in pool stream):
      - First tool_use for a (tool_name, phrase) key  → status='starting'
      - Repeat within coalescing window              → status='running', same id
      - New tool_use with a different id arrives     → emit 'complete' for the
                                                       previous, then 'starting'
      - turn_complete (result event) arrives         → emit 'complete' for any
                                                       in-flight action, then
                                                       emit turn_complete
    """
    # Pool uses {"event": "cancelled"} (SSE event-field convention) when the
    # subprocess is interrupted — check this key first before the type dispatch.
    if sdk_event.get("event") == "cancelled":
        # Clear any in-flight action without emitting complete on interrupt.
        session.last_emitted_action = None
        yield {"type": "interrupted", "session_id": session_id}
        return

    event_type = sdk_event.get("type", "")

    if event_type == "text_delta":
        yield {
            "type": "agent_text_delta",
            "session_id": session_id,
            "delta": sdk_event.get("delta", ""),
        }
        return

    if event_type == "result":
        # Synthesize 'complete' for any action still in flight.
        if session.last_emitted_action:
            yield {**session.last_emitted_action, "status": "complete"}
            session.last_emitted_action = None
        yield {
            "type": "turn_complete",
            "session_id": session_id,
            "final_text": sdk_event.get("final_text", ""),
            "tokens_used": sdk_event.get("tokens_used", 0),
        }
        return

    if event_type == "tool_use":
        tool_name = sdk_event.get("tool_name", "")
        args = sdk_event.get("args", {})
        entry = table.lookup(tool_name)

        if isinstance(entry, PassthroughEntry):
            # Passthrough tools (e.g. send_status_update) emit a status event
            # with phase='tool_call' so the frontend can show inline progress.
            yield {
                "type": "status",
                "session_id": session_id,
                "phase": "tool_call",
                "text": args.get("text", ""),
            }
            return

        phrase = table.interpolate_phrase(entry, args)
        action_id, coalesced = session.coalescing_buffer.record(tool_name, phrase)

        # If a DIFFERENT action is in flight, mark it complete before this one starts.
        if session.last_emitted_action and session.last_emitted_action["id"] != action_id:
            yield {**session.last_emitted_action, "status": "complete"}

        status = "running" if coalesced else "starting"
        event: dict = {
            "type": "agent_action",
            "session_id": session_id,
            "id": action_id,
            "tool_name": tool_name,
            "friendly_text": phrase,
            "status": status,
        }
        session.last_emitted_action = event
        yield event
        return

    if event_type == "status":
        # Forwarded from bot pipeline phase signals (bot.py / register.py calls
        # status_fn at classifier, main_reasoning, summarization transitions).
        # The caller is responsible for supplying 'phase'; default to 'main_reasoning'.
        yield {
            "type": "status",
            "session_id": session_id,
            "phase": sdk_event.get("phase", "main_reasoning"),
            "text": sdk_event.get("text", sdk_event.get("message", "")),
        }
        return

    # Unknown event — forward as status for visibility (phase unknown → main_reasoning)
    yield {
        "type": "status",
        "session_id": session_id,
        "phase": "main_reasoning",
        "text": str(sdk_event),
    }
