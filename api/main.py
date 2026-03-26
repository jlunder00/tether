from pathlib import Path
from fastapi import FastAPI, WebSocket, WebSocketDisconnect
from fastapi.staticfiles import StaticFiles
from api.routes import plan as plan_routes
from api.routes import anchors as anchor_routes
from api.routes import context as context_routes
from api.ws import manager
import api.config as cfg

FRONTEND_DIST = Path(__file__).parent.parent / "frontend" / "dist"


def create_app(db_path: Path | None = None) -> FastAPI:
    if db_path is not None:
        cfg.DB_PATH = db_path

    app = FastAPI(title="Tether")
    app.include_router(plan_routes.router, prefix="/api")
    app.include_router(anchor_routes.router, prefix="/api")
    app.include_router(context_routes.router, prefix="/api")

    @app.websocket("/ws")
    async def websocket_endpoint(websocket: WebSocket):
        await manager.connect(websocket)
        try:
            while True:
                await websocket.receive_text()
        except WebSocketDisconnect:
            manager.disconnect(websocket)

    if FRONTEND_DIST.exists():
        app.mount("/", StaticFiles(directory=str(FRONTEND_DIST), html=True), name="frontend")

    return app


app = create_app()
