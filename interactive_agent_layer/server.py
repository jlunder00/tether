"""FastAPI app for the interactive agent layer service."""
from __future__ import annotations

import json

from fastapi import FastAPI, HTTPException
from fastapi.responses import JSONResponse, StreamingResponse
from pydantic import BaseModel

from interactive_agent_layer.session import Layer, Session


class SessionStartRequest(BaseModel):
    user_id: str
    user_ws_id: str
    agent_version: str
    options: dict = {}
    user_message: str


class TurnRequest(BaseModel):
    prompt: str


class PermissionRespondRequest(BaseModel):
    approve: bool


def create_app(layer: Layer) -> FastAPI:
    app = FastAPI(title="Interactive Agent Layer")
    app.state.layer = layer

    def require_session(session_id: str) -> Session:
        session = layer.get_session(session_id)
        if session is None:
            raise HTTPException(status_code=404, detail="Session not found")
        return session

    async def check_2_5_gates(body: SessionStartRequest) -> JSONResponse | None:
        """Enforce BYOK-leakage and free-tier trial gates for tether-agent-2.5.

        Returns a 422 JSONResponse if the request is blocked, else None.
        """
        # B5b — BYOK leakage gate: block 2.5 on providers that expose prompt content.
        if layer.provider_fn is not None and layer.leaky_providers is not None:
            if layer.provider_fn(body.user_id) in layer.leaky_providers:
                return JSONResponse(
                    status_code=422,
                    content={
                        "error": "provider_unsupported_for_agent",
                        "alternatives": ["tether-agent-2.0"],
                    },
                )

        # B5a — trial counter (skipped entirely for premium users).
        if layer.trial_counter is None:
            return None

        is_paid = await layer.is_paid_fn(body.user_id) if layer.is_paid_fn else False
        if is_paid:
            return None

        allowed, remaining = await layer.trial_counter.check_and_increment(body.user_id)
        if not allowed:
            return JSONResponse(
                status_code=422,
                content={"error": "trial_exhausted", "upgrade_url": "/upgrade"},
            )
        # Publish live remaining count to the frontend picker.
        # Pass user_id so the Redis channel is keyed on the stable JWT claim,
        # not the per-connection user_ws_id.
        await layer.ws_publisher.push(
            body.user_ws_id,
            {"type": "trial_usage_update", "remaining": remaining},
            user_id=body.user_id,
        )
        return None

    @app.post("/session/start")
    async def session_start(body: SessionStartRequest):
        if body.agent_version == "tether-agent-2.5":
            blocked = await check_2_5_gates(body)
            if blocked is not None:
                return blocked

        session = layer.create_session(
            user_id=body.user_id,
            user_ws_id=body.user_ws_id,
            agent_version=body.agent_version,
            options=body.options,
        )
        return {"session_id": session.session_id}

    @app.post("/session/{session_id}/turn")
    async def session_turn(session_id: str, body: TurnRequest) -> StreamingResponse:
        require_session(session_id)

        async def event_generator():
            try:
                async for event in layer.run_turn(session_id, body.prompt):
                    yield f"data: {json.dumps(event)}\n\n"
            except Exception as exc:
                # HTTP headers are already committed — we can't change the status
                # code. Emit a turn_error event so the client gets a parseable
                # in-band signal instead of an abrupt connection close.
                import logging as _log
                _log.getLogger(__name__).exception(
                    "run_turn failed for session %s: %s", session_id, exc
                )
                error_event = {
                    "type": "turn_error",
                    "session_id": session_id,
                    "message": str(exc),
                }
                yield f"data: {json.dumps(error_event)}\n\n"

        return StreamingResponse(
            event_generator(),
            media_type="text/event-stream",
            headers={
                "Cache-Control": "no-cache",
                "X-Accel-Buffering": "no",
            },
        )

    @app.post("/session/{session_id}/interrupt")
    async def session_interrupt(session_id: str) -> dict:
        require_session(session_id)
        await layer.interrupt(session_id)
        return {"status": "interrupted"}

    @app.post("/session/{session_id}/end")
    async def session_end(session_id: str) -> dict:
        require_session(session_id)
        layer.end_session(session_id)
        return {"status": "ended"}

    @app.get("/session/{session_id}/status")
    async def session_status(session_id: str) -> dict:
        session = require_session(session_id)
        return {
            "session_id": session.session_id,
            "user_id": session.user_id,
            "agent_version": session.agent_version,
            "turn_count": session.turn_count,
            "created_at": session.created_at,
        }

    @app.post("/permission/{request_id}/respond")
    async def permission_respond(request_id: str, body: PermissionRespondRequest) -> dict:
        for session in layer.sessions.values():
            future = session.permission_pending.get(request_id)
            if future is not None and not future.done():
                future.set_result(body.approve)
                return {"status": "ok"}
        raise HTTPException(status_code=404, detail="Permission request not found")

    return app
