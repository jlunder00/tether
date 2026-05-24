"""Agent pool manager HTTP service — FastAPI app with pool endpoints."""
from __future__ import annotations

import asyncio
import dataclasses
import json
import logging
from contextlib import asynccontextmanager
from typing import Any, AsyncIterator

from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import JSONResponse, PlainTextResponse, StreamingResponse
from pydantic import BaseModel, Field

from .config import AgentPoolConfig, load_pool_config
from .metrics import PoolMetrics
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
    # Optional token tracking — passed by the layer after a turn completes
    user_id: str | None = None
    input_tokens: int | None = None
    output_tokens: int | None = None


class QueryRequest(BaseModel):
    prompt: str
    session_id: str = "default"


class HintRequest(BaseModel):
    user_id: str
    options_hash: str
    options: dict[str, Any] = Field(default_factory=dict)


class ControlResponseRequest(BaseModel):
    request_id: str
    subtype: str
    decision: str  # "allow" | "deny"
    denial_message: str | None = None


# ---------------------------------------------------------------------------
# Token usage async write — no-op if DB pool unavailable
# ---------------------------------------------------------------------------

# Strong references to in-flight token-write tasks prevent GC from silently
# dropping them before they complete (asyncio creates a weak reference only).
_token_write_tasks: set[asyncio.Task] = set()


def write_token_usage_async(user_id: str, input_tokens: int, output_tokens: int) -> None:
    """Fire-and-forget token usage DB write.

    Creates an asyncio task to write token counts to the ``token_usage`` table.
    The task is intentionally not awaited — callers on the hot path (release
    endpoint) must not block on the DB write.

    A strong reference is kept in ``_token_write_tasks`` until the task
    completes, preventing the GC from silently dropping in-flight writes.

    If the event loop is not running or the DB layer is unavailable, the
    failure is logged at WARNING level (not silently swallowed).
    """
    try:
        from db.pg_queries.token_usage import record_token_usage
        task = asyncio.create_task(
            record_token_usage(user_id, input_tokens, output_tokens),
            name=f"token-usage-{user_id}",
        )
        _token_write_tasks.add(task)
        task.add_done_callback(_token_write_tasks.discard)
    except RuntimeError as exc:
        # RuntimeError: no running event loop — should not happen in an async
        # handler but log at warning so it's visible, not silently dropped.
        log.warning("write_token_usage_async: no event loop — token write dropped: %s", exc)
    except Exception:
        log.warning("write_token_usage_async: failed to schedule token write", exc_info=True)


# ---------------------------------------------------------------------------
# App factory
# ---------------------------------------------------------------------------

def build_app(
    pool: Pool | None = None,
    refill: RefillLoop | None = None,
    metrics: PoolMetrics | None = None,
) -> FastAPI:
    """Build the FastAPI app.

    ``pool``, ``refill``, and ``metrics`` may be injected for testing; if
    omitted they are constructed from the TetherConfig at startup.
    """
    @asynccontextmanager
    async def lifespan(app: FastAPI) -> AsyncIterator[None]:
        if pool is not None:
            app.state.pool = pool
            app.state.refill = refill or RefillLoop(pool)
            app.state.metrics = metrics or PoolMetrics()
        else:
            try:
                from config.loader import TetherConfig
                cfg = load_pool_config(TetherConfig())
            except Exception:
                cfg = AgentPoolConfig()
            app.state.pool = Pool(cfg)
            app.state.refill = RefillLoop(app.state.pool)
            app.state.metrics = PoolMetrics()

        # Wire metrics into pool so acquire/release/refill events are recorded
        app.state.pool._metrics = app.state.metrics
        app.state.metrics.attach_pool(app.state.pool)

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
                user_id=req.user_id,
            )
        except PoolExhausted:
            return JSONResponse(
                status_code=503,
                content={"error": "pool_exhausted", "retry_after_seconds": 5},
            )
        return JSONResponse({"handle_id": handle_id, **meta})

    # -----------------------------------------------------------------------
    # POST /handle/{handle_id}/query  — SSE stream
    #
    # Runs two concurrent tasks inside the stream generator:
    #   - SDK receive_response() — may block when can_use_tool fires
    #   - bridge event queue drain — emits control_request events while
    #     the SDK callback awaits a control_response
    #
    # Callers that ignore control_request events still work: the callback
    # times out to deny and the stream resumes normally.
    # -----------------------------------------------------------------------
    @app.post("/handle/{handle_id}/query")
    async def query(handle_id: str, req: QueryRequest, request: Request) -> StreamingResponse:
        the_pool: Pool = request.app.state.pool
        async with the_pool._lock:
            sub = the_pool._active.get(handle_id)
        if sub is None:
            raise HTTPException(status_code=404, detail="handle not found")

        bridge = the_pool.control_bridge

        async def event_stream() -> AsyncIterator[str]:
            # Register a per-handle SSE queue so bridge.request() can enqueue
            # control_request events while the SDK callback awaits.
            ctrl_queue = bridge.register_handle(handle_id)
            # Unified output queue: both SDK msgs and ctrl events drain here.
            out: asyncio.Queue[tuple[str, Any]] = asyncio.Queue()

            async def _run_sdk() -> None:
                try:
                    await sub.proc.query(req.prompt, session_id=req.session_id)
                    async for msg in sub.proc.receive_response():
                        await out.put(("msg", msg))
                finally:
                    await out.put(("done", None))

            async def _run_ctrl() -> None:
                """Forward control events from bridge queue → output queue."""
                while True:
                    evt = await ctrl_queue.get()
                    await out.put(("ctrl", evt))

            sdk_task = asyncio.create_task(_run_sdk())
            ctrl_task = asyncio.create_task(_run_ctrl())

            try:
                while True:
                    kind, data = await out.get()
                    if kind == "done":
                        break
                    if kind == "ctrl":
                        yield f"data: {json.dumps(data)}\n\n"
                    else:
                        yield f"data: {json.dumps(_serialise_msg(data))}\n\n"
                yield "data: [DONE]\n\n"
            except asyncio.CancelledError:
                yield 'data: {"event": "cancelled"}\n\n'
            except Exception:
                log.exception("Error streaming query for handle %s", handle_id)
                yield 'data: {"error": "internal_error"}\n\n'
            finally:
                ctrl_task.cancel()
                sdk_task.cancel()
                bridge.deregister_handle(handle_id)

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

        # Fire-and-forget token write when the caller reports usage
        if req.user_id and req.input_tokens is not None and req.output_tokens is not None:
            write_token_usage_async(req.user_id, req.input_tokens, req.output_tokens)

    # -----------------------------------------------------------------------
    # GET /status
    # -----------------------------------------------------------------------
    @app.get("/status")
    async def status(request: Request) -> dict:
        the_pool: Pool = request.app.state.pool
        return the_pool.status()

    # -----------------------------------------------------------------------
    # GET /metrics  — Prometheus text exposition format
    # -----------------------------------------------------------------------
    @app.get("/metrics")
    async def metrics_endpoint(request: Request) -> PlainTextResponse:
        """Expose pool metrics in Prometheus text format.

        Counters, histograms, and pool size gauges are included.
        Scrape with Prometheus or read directly for debugging.
        """
        the_metrics: PoolMetrics = request.app.state.metrics
        text = the_metrics.render_text()
        return PlainTextResponse(content=text, media_type="text/plain; version=0.0.4")

    # -----------------------------------------------------------------------
    # POST /hint
    # -----------------------------------------------------------------------
    @app.post("/hint", status_code=202)
    async def hint(req: HintRequest, request: Request) -> dict:
        the_refill: RefillLoop = request.app.state.refill
        # Diagnostic: log hint receipt with redacted summary so we can confirm
        # what reached the pool service and correlate with refill-side logs.
        from .pool import _options_summary  # local import — keep module deps flat
        log.info(
            "pool_server.hint_recv user_id=%s options_hash=%s summary=%r",
            req.user_id, req.options_hash, _options_summary(req.options),
        )
        asyncio.create_task(the_refill.hint(req.options_hash, req.options))
        return {"queued": True}

    # -----------------------------------------------------------------------
    # POST /handle/{handle_id}/control_response
    #
    # Resolves a pending can_use_tool permission request.
    # 204 on success; 404 if request_id unknown or already resolved.
    # -----------------------------------------------------------------------
    @app.post("/handle/{handle_id}/control_response", status_code=204)
    async def control_response(
        handle_id: str,
        req: ControlResponseRequest,
        request: Request,
    ) -> None:
        the_pool: Pool = request.app.state.pool
        payload: dict[str, Any] = {"decision": req.decision}
        if req.denial_message is not None:
            payload["denial_message"] = req.denial_message
        resolved = the_pool.control_bridge.respond(req.request_id, payload)
        if not resolved:
            raise HTTPException(
                status_code=404,
                detail=f"request_id {req.request_id!r} not found or already resolved",
            )

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
