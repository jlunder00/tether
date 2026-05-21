"""Session dataclass and Layer class."""
from __future__ import annotations

import dataclasses
import json
import time
import uuid
from collections.abc import Callable
from typing import AsyncIterator, Any

from interactive_agent_layer.coalescing import CoalescingBuffer
from interactive_agent_layer.config import get_auto_approve_user_actions
from interactive_agent_layer.permissions import PermissionGate
from interactive_agent_layer.pool_client import PoolClient
from interactive_agent_layer.translation import (
    BackgroundEntry,
    BackgroundHiddenEntry,
    PassthroughEntry,
    TranslationTable,
    UserActionEntry,
)
from interactive_agent_layer.ws_publisher import WSPublisher


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
    ) -> Session:
        session_id = str(uuid.uuid4())
        session = Session(
            session_id=session_id,
            user_id=user_id,
            user_ws_id=user_ws_id,
            agent_version=agent_version,
            options=options,
        )
        self.sessions[session_id] = session
        return session

    def get_session(self, session_id: str) -> Session | None:
        return self.sessions.get(session_id)

    def end_session(self, session_id: str) -> None:
        self.sessions.pop(session_id, None)

    async def run_turn(self, session_id: str, prompt: str) -> AsyncIterator[dict]:
        session = self.sessions[session_id]  # raises KeyError if missing
        options_hash = hash(json.dumps(session.options, sort_keys=True))
        gate = PermissionGate(
            translation_table=self.translation_table,
            ws_publisher=self.ws_publisher,
            session=session,
            auto_approve_user_actions=get_auto_approve_user_actions(),
        )
        handle = await self.pool_client.acquire(session.user_id, options_hash)
        session.active_handles.append(handle)
        try:
            async for sdk_event in self.pool_client.query(
                handle, prompt, can_use_tool=gate.can_use_tool
            ):
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


async def _translate_event(
    session_id: str,
    sdk_event: dict,
    table: TranslationTable,
    session: Session,
) -> AsyncIterator[dict]:
    """Translate a raw SDK event to one or more layer events."""
    event_type = sdk_event.get("type", "")

    if event_type == "text_delta":
        yield {
            "type": "agent_text_delta",
            "session_id": session_id,
            "delta": sdk_event.get("delta", ""),
        }
        return

    if event_type == "result":
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
            # Emit the status text directly
            yield {
                "type": "status",
                "session_id": session_id,
                "message": args.get("text", ""),
            }
            return

        phrase = table.interpolate_phrase(entry, args)
        action_id, coalesced = session.coalescing_buffer.record(tool_name, phrase)
        yield {
            "type": "agent_action",
            "session_id": session_id,
            "action_id": action_id,
            "action": phrase,
            "coalesced": coalesced,
        }
        return

    if event_type == "status":
        yield {
            "type": "status",
            "session_id": session_id,
            "message": sdk_event.get("message", ""),
        }
        return

    # Unknown event — forward as status for visibility
    yield {"type": "status", "session_id": session_id, "message": str(sdk_event)}
