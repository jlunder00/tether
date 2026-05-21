"""FastAPI app for the interactive agent layer service."""
from __future__ import annotations

import json

from fastapi import FastAPI, HTTPException
from fastapi.responses import StreamingResponse
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

    @app.post("/session/start")
    async def session_start(body: SessionStartRequest) -> dict:
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
            async for event in layer.run_turn(session_id, body.prompt):
                yield f"data: {json.dumps(event)}\n\n"

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
