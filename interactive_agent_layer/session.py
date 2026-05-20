"""Session dataclass and Layer class."""
from __future__ import annotations

import dataclasses
import json
import time
import uuid
from typing import AsyncIterator

from interactive_agent_layer.pool_client import PoolClient
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


class Layer:
    def __init__(self, pool_client: PoolClient, ws_publisher: WSPublisher) -> None:
        self.sessions: dict[str, Session] = {}
        self.pool_client = pool_client
        self.ws_publisher = ws_publisher

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
        handle = await self.pool_client.acquire(session.user_id, options_hash)
        session.active_handles.append(handle)
        try:
            async for sdk_event in self.pool_client.query(handle, prompt):
                layer_event = _translate_event(session_id, sdk_event)
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


def _translate_event(session_id: str, sdk_event: dict) -> dict:
    """Translate a raw SDK event to a layer event (B1 naive forwarding)."""
    event_type = sdk_event.get("type", "")
    if event_type == "text_delta":
        return {
            "type": "agent_text_delta",
            "session_id": session_id,
            "delta": sdk_event.get("delta", ""),
        }
    if event_type == "result":
        return {
            "type": "turn_complete",
            "session_id": session_id,
            "final_text": sdk_event.get("final_text", ""),
            "tokens_used": sdk_event.get("tokens_used", 0),
        }
    return {
        "type": "status",
        "session_id": session_id,
        "message": str(sdk_event),
    }
