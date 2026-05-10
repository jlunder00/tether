import asyncio
import json
import logging
import asyncpg
from werkzeug.security import safe_join

import os
_log_level = logging.DEBUG if os.environ.get("TETHER_LOG_LEVEL", "").upper() == "DEBUG" else logging.INFO
logging.basicConfig(level=_log_level)
# basicConfig is a no-op if uvicorn already added handlers to the root logger,
# so set levels explicitly to guarantee they take effect.
logging.getLogger().setLevel(_log_level)
logging.getLogger("api").setLevel(_log_level)
from contextlib import asynccontextmanager
from pathlib import Path
from fastapi import Depends, FastAPI, HTTPException, Request, WebSocket, WebSocketDisconnect
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
from api.routes import integrations as integrations_routes
from api.routes import api_keys as api_keys_routes
from api.routes import events as events_routes
from api.routes import preferences as preferences_routes
from api.routes import ical as ical_routes
from api.ws import manager
from api.auth import auth_dependency, decode_jwt
from api.limiter import limiter
from db.pool_middleware import lifespan as _pool_lifespan
from db.pg_queries.errors import StaleReadError
import db.postgres as pg
import api.config as cfg

_DEFAULT_JWT_SECRET = "dev-secret-change-in-production"


def _check_jwt_secret(secret: str) -> None:
    """Raise RuntimeError if *secret* is the insecure default value."""
    if secret == _DEFAULT_JWT_SECRET:
        raise RuntimeError(
            "TETHER_JWT_SECRET must be set to a secure value in production"
        )

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
    import os as _startup_os
    if _startup_os.environ.get("ENVIRONMENT") == "production":
        _check_jwt_secret(cfg.JWT_SECRET)
    async with _pool_lifespan(app):
        # Initialize credentials vault if key is configured
        from api.credentials_vault import CredentialsVault
        if cfg.VAULT_KEY:
            app.state.vault = CredentialsVault(app.state.pool, cfg.VAULT_KEY)
        else:
            app.state.vault = None

        # Register Telegram webhook if webhook URL is configured.
        # When TELEGRAM_WEBHOOK_URL is not set, polling mode is used (no-op here).
        webhook_url = _startup_os.environ.get("TELEGRAM_WEBHOOK_URL")
        if webhook_url:
            try:
                from bot.webhook_setup import register_webhook
                from config.loader import config as tether_config
                bot_token = tether_config.get("telegram.bot_token", "")
                secret = _startup_os.environ.get("TELEGRAM_WEBHOOK_SECRET", "")
                await register_webhook(bot_token, webhook_url, secret)
            except Exception as _wh_exc:
                logging.getLogger(__name__).warning(
                    "lifespan: webhook registration failed (bot may not receive messages): %s",
                    _wh_exc,
                )

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
        allow_origins=cfg.ALLOWED_ORIGINS,
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )

    # Rate limiting — attach limiter to app state so slowapi can find it.
    # When TETHER_DISABLE_RATE_LIMITS=1 the limiter is a no-op; no exception
    # handler is needed in that case.
    import os as _os
    if not _os.environ.get("TETHER_DISABLE_RATE_LIMITS"):
        try:
            from slowapi import _rate_limit_exceeded_handler
            from slowapi.errors import RateLimitExceeded
            app.state.limiter = limiter
            app.add_exception_handler(RateLimitExceeded, _rate_limit_exceeded_handler)
        except ImportError:
            pass  # slowapi not installed — rate limiting skipped

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
    app.include_router(integrations_routes.router, prefix="/api")
    app.include_router(api_keys_routes.router, prefix="/api")
    app.include_router(events_routes.router, prefix="/api")
    app.include_router(preferences_routes.router, prefix="/api")
    app.include_router(ical_routes.router, prefix="/api")

    # --- Premium plugin hook ---
    try:
        from tether_premium.register import register_premium_routes
        register_premium_routes(app)
    except ImportError:
        pass

    @app.get("/api/health")
    async def health():
        """Unauthenticated liveness check. Used by supervisord wait loop."""
        return {"status": "ok"}

    @app.get("/api/version")
    async def version():
        """Unauthenticated version check. Returns tether and premium versions."""
        import os as _version_os
        from importlib.metadata import version as _pkg_ver, PackageNotFoundError as _PKGNf
        result: dict = {"tether": _version_os.environ.get("TETHER_VERSION", "dev")}
        try:
            result["premium"] = _pkg_ver("tether-premium")
        except _PKGNf:
            pass  # community edition — premium not installed
        return result

    @app.post("/api/notify")
    async def notify(request: Request, _auth=Depends(auth_dependency)):
        if not request.state.is_admin:
            raise HTTPException(status_code=403, detail="Admin only")
        await manager.broadcast({"type": "plan_updated"})
        await manager.broadcast({"type": "context_updated"})
        return {"ok": True}

    @app.websocket("/ws")
    async def websocket_endpoint(websocket: WebSocket):
        import db.pg_queries.api_keys as _api_keys_queries

        token = websocket.cookies.get("tether_token")
        if token:
            try:
                payload = decode_jwt(token)
                user_id = payload["user_id"]
                is_admin = payload.get("is_admin", False)
                is_bot_service = payload.get("is_bot_service", False)
            except Exception:
                await websocket.close(code=1008)
                return

            # Bot service path: register with per-user delegation filtering.
            # Backward-compat: is_admin path (__bot__ channel) retained until PR 7.
            if is_bot_service:
                delegated = await _api_keys_queries.get_delegated_user_ids(
                    websocket.app.state.pool, user_id
                )
                await websocket.accept()
                manager.register_bot(websocket, user_id, delegated)
                try:
                    while True:
                        await websocket.receive_text()
                except (WebSocketDisconnect, RuntimeError):
                    pass
                finally:
                    manager.disconnect_bot(user_id)
                return

            await manager.connect(websocket, user_id)
            if is_admin:
                manager.register_only(websocket, "__bot__")
            try:
                while True:
                    await websocket.receive_text()
            except (WebSocketDisconnect, RuntimeError):
                pass
            finally:
                manager.disconnect(websocket, user_id)
                if is_admin:
                    manager.disconnect(websocket, "__bot__")
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
                is_admin = payload.get("is_admin", False)
                is_bot_service = payload.get("is_bot_service", False)
            except Exception:
                await websocket.close(code=1008)
                return

            # Bot service path via message auth.
            if is_bot_service:
                delegated = await _api_keys_queries.get_delegated_user_ids(
                    websocket.app.state.pool, user_id
                )
                manager.register_bot(websocket, user_id, delegated)
                try:
                    while True:
                        await websocket.receive_text()
                except (WebSocketDisconnect, RuntimeError):
                    pass
                finally:
                    manager.disconnect_bot(user_id)
                return

            manager.register_only(websocket, user_id)
            if is_admin:
                manager.register_only(websocket, "__bot__")
            try:
                while True:
                    await websocket.receive_text()
            except (WebSocketDisconnect, RuntimeError):
                pass
            finally:
                manager.disconnect(websocket, user_id)
                if is_admin:
                    manager.disconnect(websocket, "__bot__")

    if FRONTEND_DIST.exists():
        # Serve static assets (JS, CSS, images) directly
        app.mount("/assets", StaticFiles(directory=str(FRONTEND_DIST / "assets")), name="assets")

        # SPA fallback: serve index.html for all non-API routes
        # so Vue Router can handle client-side routing
        from fastapi.responses import FileResponse

        @app.get("/{full_path:path}")
        async def serve_spa(full_path: str):
            # safe_join is a CodeQL-recognised sanitizer: it returns None if
            # full_path would escape FRONTEND_DIST (e.g. via '../' sequences),
            # preventing path-traversal without requiring taint-flow analysis.
            safe = safe_join(str(FRONTEND_DIST), full_path)
            if safe is None:
                raise HTTPException(status_code=404)
            safe_path = Path(safe)
            if safe_path.is_file():
                return FileResponse(safe_path)
            return FileResponse(FRONTEND_DIST / "index.html")

    return app


app = create_app()
