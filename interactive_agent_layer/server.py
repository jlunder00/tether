"""FastAPI app for the interactive agent layer service."""
from __future__ import annotations

import json
from typing import Any

from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import StreamingResponse
from pydantic import BaseModel

from interactive_agent_layer.session import Layer


class SessionStartRequest(BaseModel):
    user_id: str
    user_ws_id: str
    agent_version: str
    options: dict = {}
    user_message: str


class TurnRequest(BaseModel):
    prompt: str


def create_app(layer: Layer) -> FastAPI:
    app = FastAPI(title="Interactive Agent Layer")
    app.state.layer = layer

    @app.post("/session/start")
    async def session_start(body: SessionStartRequest, request: Request) -> dict:
        lyr: Layer = request.app.state.layer
        session = lyr.create_session(
            user_id=body.user_id,
            user_ws_id=body.user_ws_id,
            agent_version=body.agent_version,
            options=body.options,
        )
        return {"session_id": session.session_id}

    @app.post("/session/{session_id}/turn")
    async def session_turn(
        session_id: str, body: TurnRequest, request: Request
    ) -> StreamingResponse:
        lyr: Layer = request.app.state.layer
        if lyr.get_session(session_id) is None:
            raise HTTPException(status_code=404, detail="Session not found")

        async def event_generator():
            async for event in lyr.run_turn(session_id, body.prompt):
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
    async def session_interrupt(session_id: str, request: Request) -> dict:
        lyr: Layer = request.app.state.layer
        if lyr.get_session(session_id) is None:
            raise HTTPException(status_code=404, detail="Session not found")
        await lyr.interrupt(session_id)
        return {"status": "interrupted"}

    @app.post("/session/{session_id}/end")
    async def session_end(session_id: str, request: Request) -> dict:
        lyr: Layer = request.app.state.layer
        if lyr.get_session(session_id) is None:
            raise HTTPException(status_code=404, detail="Session not found")
        lyr.end_session(session_id)
        return {"status": "ended"}

    @app.get("/session/{session_id}/status")
    async def session_status(session_id: str, request: Request) -> dict:
        lyr: Layer = request.app.state.layer
        session = lyr.get_session(session_id)
        if session is None:
            raise HTTPException(status_code=404, detail="Session not found")
        return {
            "session_id": session.session_id,
            "user_id": session.user_id,
            "agent_version": session.agent_version,
            "turn_count": session.turn_count,
            "created_at": session.created_at,
        }

    return app
