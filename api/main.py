from pathlib import Path
from fastapi import FastAPI, WebSocket, WebSocketDisconnect
from fastapi.middleware.cors import CORSMiddleware
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
from api.ws import manager
from api.auth import decode_jwt
from db.auth_schema import init_auth_db
import api.config as cfg

FRONTEND_DIST = Path(__file__).parent.parent / "frontend" / "dist"


def create_app(db_path: Path | None = None) -> FastAPI:
    if db_path is not None:
        cfg.DB_PATH = db_path

    cfg.CONFIG_DIR.mkdir(parents=True, exist_ok=True)
    cfg.USERS_DB_DIR.mkdir(parents=True, exist_ok=True)
    init_auth_db(cfg.AUTH_DB_PATH)

    app = FastAPI(title="Tether")

    app.add_middleware(
        CORSMiddleware,
        allow_origins=["*"],
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )

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

    @app.post("/api/notify")
    async def notify():
        await manager.broadcast({"type": "plan_updated"})
        await manager.broadcast({"type": "context_updated"})
        return {"ok": True}

    @app.websocket("/ws")
    async def websocket_endpoint(websocket: WebSocket):
        token = websocket.cookies.get("tether_token")
        if not token:
            await websocket.close(code=1008)
            return
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
