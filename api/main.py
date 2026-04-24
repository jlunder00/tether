import asyncio
import json
import logging
import asyncpg

logging.basicConfig(level=logging.INFO)
from contextlib import asynccontextmanager
from pathlib import Path
from fastapi import FastAPI, WebSocket, WebSocketDisconnect
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from fastapi.staticfiles import StaticFiles
from api.routes import plan as plan_routes
from api.routes import anchors as anchor_routes
from api.routes import context as context_routes
from api.routes import logs as logs_routes
from api.routes import tasks as tasks_routes
from api.routes import milestones as milestones_routes
from api.routes import auth as auth_routes
from api.routes import dependencies as dependencies_routes
from api.routes import links as links_routes
from api.routes import llm_config as llm_config_routes
from api.routes import sessions as sessions_routes
from api.routes import bot as bot_routes
from api.routes import kanban as kanban_routes
from api.routes import nodes as nodes_routes
from api.routes import settings as settings_routes
from api.routes import connections as connections_routes
from api.routes import meetings as meetings_routes
from api.routes import events as events_routes
from api.ws import manager
from api.auth import decode_jwt
from db.pool_middleware import lifespan as _pool_lifespan
from db.pg_queries.errors import StaleReadError
import db.postgres as pg
import api.config as cfg

FRONTEND_DIST = Path(__file__).parent.parent / "frontend" / "dist"


async def _expiry_loop(app):
    from db.pg_queries.scheduling import expire_old_requests, get_meeting_request, get_participants
    while True:
        await asyncio.sleep(3600)
        try:
            async with pg.get_conn(app.state.pool) as conn:
                expired_ids = await expire_old_requests(conn)
            for req_id in expired_ids:
                async with pg.get_conn(app.state.pool) as conn:
                    req = await get_meeting_request(conn, req_id)
                if req:
                    for uid in get_participants(req):
                        await manager.broadcast({"type": "meeting_cancelled", "request_id": req_id}, uid)
        except Exception:
            pass


@asynccontextmanager
async def lifespan(app):
    async with _pool_lifespan(app):
        task = asyncio.create_task(_expiry_loop(app))
        yield
        task.cancel()
        try:
            await task
        except asyncio.CancelledError:
            pass


def create_app(lifespan_override=None) -> FastAPI:
    cfg.CONFIG_DIR.mkdir(parents=True, exist_ok=True)
    actual_lifespan = lifespan_override if lifespan_override is not None else lifespan

    app = FastAPI(title="Tether", lifespan=actual_lifespan)

    app.add_middleware(
        CORSMiddleware,
        allow_origins=["*"],
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )

    @app.exception_handler(ValueError)
    async def value_error_handler(request, exc):
        return JSONResponse(status_code=400, content={"detail": str(exc)})

    @app.exception_handler(StaleReadError)
    async def stale_read_handler(request, exc):
        return JSONResponse(status_code=409, content={"current_version": exc.current_version})

    @app.exception_handler(asyncpg.UniqueViolationError)
    async def unique_violation_handler(request, exc):
        return JSONResponse(status_code=409, content={"detail": "Resource already exists (duplicate)"})

    @app.exception_handler(asyncpg.ForeignKeyViolationError)
    async def fk_violation_handler(request, exc):
        return JSONResponse(status_code=422, content={"detail": "Referenced resource not found"})

    @app.exception_handler(asyncpg.IntegrityConstraintViolationError)
    async def integrity_handler(request, exc):
        return JSONResponse(status_code=400, content={"detail": "Database constraint violated"})

    app.include_router(auth_routes.router)  # No /api prefix — OAuth callbacks need clean /auth URLs
    app.include_router(plan_routes.router, prefix="/api")
    app.include_router(anchor_routes.router, prefix="/api")
    app.include_router(milestones_routes.router, prefix="/api")  # must be before context_routes (overlapping {subject:path} wildcard)
    app.include_router(context_routes.router, prefix="/api")
    app.include_router(logs_routes.router, prefix="/api")
    app.include_router(tasks_routes.router, prefix="/api")
    app.include_router(dependencies_routes.router, prefix="/api")
    app.include_router(links_routes.router, prefix="/api")
    app.include_router(llm_config_routes.router, prefix="/api")
    app.include_router(sessions_routes.router, prefix="/api")
    app.include_router(bot_routes.router, prefix="/api")
    app.include_router(kanban_routes.router, prefix="/api")
    app.include_router(nodes_routes.router, prefix="/api")
    app.include_router(settings_routes.router, prefix="/api")
    app.include_router(connections_routes.router, prefix="/api")
    app.include_router(meetings_routes.router, prefix="/api")
    app.include_router(events_routes.router, prefix="/api")

    # --- Premium plugin hook ---
    try:
        from tether_premium.register import register_premium_routes
        register_premium_routes(app)
    except ImportError:
        pass

    @app.post("/api/notify")
    async def notify():
        await manager.broadcast({"type": "plan_updated"})
        await manager.broadcast({"type": "context_updated"})
        return {"ok": True}

    @app.websocket("/ws")
    async def websocket_endpoint(websocket: WebSocket):
        token = websocket.cookies.get("tether_token")
        if token:
            try:
                payload = decode_jwt(token)
                user_id = payload["user_id"]
            except Exception:
                await websocket.close(code=1008)
                return
            await manager.connect(websocket, user_id)
            try:
                while True:
                    await websocket.receive_text()
            except WebSocketDisconnect:
                manager.disconnect(websocket, user_id)
        else:
            await websocket.accept()
            try:
                raw = await asyncio.wait_for(websocket.receive_text(), timeout=10.0)
                msg = json.loads(raw)
            except Exception:
                await websocket.close(code=1008)
                return
            if msg.get("type") != "auth" or not msg.get("token"):
                await websocket.close(code=1008)
                return
            try:
                payload = decode_jwt(msg["token"])
                user_id = payload["user_id"]
            except Exception:
                await websocket.close(code=1008)
                return
            manager._connections.setdefault(user_id, []).append(websocket)
            try:
                while True:
                    await websocket.receive_text()
            except WebSocketDisconnect:
                manager.disconnect(websocket, user_id)

    if FRONTEND_DIST.exists():
        # Serve static assets (JS, CSS, images) directly
        app.mount("/assets", StaticFiles(directory=str(FRONTEND_DIST / "assets")), name="assets")

        # SPA fallback: serve index.html for all non-API routes
        # so Vue Router can handle client-side routing
        from fastapi.responses import FileResponse

        @app.get("/{full_path:path}")
        async def serve_spa(full_path: str):
            # If it's a real file in dist (e.g., favicon.ico), serve it
            file_path = FRONTEND_DIST / full_path
            if full_path and file_path.is_file():
                return FileResponse(file_path)
            return FileResponse(FRONTEND_DIST / "index.html")

    return app


app = create_app()
