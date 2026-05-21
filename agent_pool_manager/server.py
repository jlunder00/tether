"""Agent pool manager HTTP service — FastAPI app with 5 pool endpoints."""
from __future__ import annotations

import asyncio
import dataclasses
import json
import logging
from contextlib import asynccontextmanager
from typing import Any, AsyncIterator

from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import JSONResponse, StreamingResponse
from pydantic import BaseModel, Field

from .config import AgentPoolConfig, load_pool_config
from .pool import Pool, PoolExhausted
from .refill import RefillLoop

log = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Request / response models
# ---------------------------------------------------------------------------

class AcquireRequest(BaseModel):
    user_id: str
    options_hash: str
    options: dict[str, Any] = Field(default_factory=dict)
    timeout_seconds: float | None = None


class ReleaseRequest(BaseModel):
    reusable: bool = False


class QueryRequest(BaseModel):
    prompt: str
    session_id: str = "default"


class HintRequest(BaseModel):
    user_id: str
    options_hash: str
    options: dict[str, Any] = Field(default_factory=dict)


# ---------------------------------------------------------------------------
# App factory
# ---------------------------------------------------------------------------

def build_app(
    pool: Pool | None = None,
    refill: RefillLoop | None = None,
) -> FastAPI:
    """Build the FastAPI app.

    ``pool`` and ``refill`` may be injected for testing; if omitted they are
    constructed from the TetherConfig at startup.
    """
    @asynccontextmanager
    async def lifespan(app: FastAPI) -> AsyncIterator[None]:
        if pool is not None:
            app.state.pool = pool
            app.state.refill = refill or RefillLoop(pool)
        else:
            try:
                from config.loader import TetherConfig
                cfg = load_pool_config(TetherConfig())
            except Exception:
                cfg = AgentPoolConfig()
            app.state.pool = Pool(cfg)
            app.state.refill = RefillLoop(app.state.pool)

        app.state.refill.start()
        log.info("Agent pool manager started")
        yield
        app.state.refill.stop()
        log.info("Agent pool manager shutting down")

    app = FastAPI(title="agent-pool-manager", lifespan=lifespan)

    # -----------------------------------------------------------------------
    # POST /acquire
    # -----------------------------------------------------------------------
    @app.post("/acquire")
    async def acquire(request: Request, req: AcquireRequest) -> JSONResponse:
        the_pool: Pool = request.app.state.pool
        try:
            handle_id, meta = await the_pool.acquire(
                req.options_hash,
                req.options,
                timeout=req.timeout_seconds,
            )
        except PoolExhausted:
            return JSONResponse(
                status_code=503,
                content={"error": "pool_exhausted", "retry_after_seconds": 5},
            )
        return JSONResponse({"handle_id": handle_id, **meta})

    # -----------------------------------------------------------------------
    # POST /handle/{handle_id}/query  — SSE stream
    # -----------------------------------------------------------------------
    @app.post("/handle/{handle_id}/query")
    async def query(handle_id: str, req: QueryRequest, request: Request) -> StreamingResponse:
        the_pool: Pool = request.app.state.pool
        async with the_pool._lock:
            sub = the_pool._active.get(handle_id)
        if sub is None:
            raise HTTPException(status_code=404, detail="handle not found")

        async def event_stream() -> AsyncIterator[str]:
            try:
                await sub.proc.query(req.prompt, session_id=req.session_id)
                async for msg in sub.proc.receive_response():
                    payload = json.dumps(_serialise_msg(msg))
                    yield f"data: {payload}\n\n"
                yield "data: [DONE]\n\n"
            except asyncio.CancelledError:
                yield 'data: {"event": "cancelled"}\n\n'
            except Exception:
                log.exception("Error streaming query for handle %s", handle_id)
                yield 'data: {"error": "internal_error"}\n\n'

        return StreamingResponse(event_stream(), media_type="text/event-stream")

    # -----------------------------------------------------------------------
    # POST /handle/{handle_id}/interrupt
    # -----------------------------------------------------------------------
    @app.post("/handle/{handle_id}/interrupt", status_code=204)
    async def interrupt(handle_id: str, request: Request) -> None:
        the_pool: Pool = request.app.state.pool
        try:
            await the_pool.interrupt(handle_id)
        except KeyError:
            raise HTTPException(status_code=404, detail="handle not found")

    # -----------------------------------------------------------------------
    # POST /handle/{handle_id}/release
    # -----------------------------------------------------------------------
    @app.post("/handle/{handle_id}/release", status_code=204)
    async def release(handle_id: str, req: ReleaseRequest, request: Request) -> None:
        the_pool: Pool = request.app.state.pool
        async with the_pool._lock:
            exists = handle_id in the_pool._active
        if not exists:
            raise HTTPException(status_code=404, detail="handle not found")
        await the_pool.release(handle_id, reusable=req.reusable)

    # -----------------------------------------------------------------------
    # GET /status
    # -----------------------------------------------------------------------
    @app.get("/status")
    async def status(request: Request) -> dict:
        the_pool: Pool = request.app.state.pool
        return the_pool.status()

    # -----------------------------------------------------------------------
    # POST /hint
    # -----------------------------------------------------------------------
    @app.post("/hint", status_code=202)
    async def hint(req: HintRequest, request: Request) -> dict:
        the_refill: RefillLoop = request.app.state.refill
        asyncio.create_task(the_refill.hint(req.options_hash, req.options))
        return {"queued": True}

    return app


# ---------------------------------------------------------------------------
# Serialisation helper
# ---------------------------------------------------------------------------

def _serialise_msg(msg: Any) -> dict:
    """Convert an SDK message to a JSON-serialisable dict."""
    if dataclasses.is_dataclass(msg):
        return dataclasses.asdict(msg)
    try:
        return vars(msg)
    except TypeError:
        return {"raw": str(msg)}
