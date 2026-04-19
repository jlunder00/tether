from fastapi import APIRouter, Depends, Request
from pydantic import BaseModel
import asyncpg
from db.pg_queries import get_anchors, upsert_anchor, delete_anchor
from db.pool_middleware import get_db_conn
from bot.crontab import sync_crontab
from api.ws import manager
from api.auth import auth_dependency

router = APIRouter()


class AnchorUpdate(BaseModel):
    name: str
    time: str
    duration_minutes: int
    flexibility: str
    strictness: int
    color: str
    position: int
    followup_config: dict | None = None


@router.get("/anchors")
async def get_anchors_route(_auth=Depends(auth_dependency),
                            conn: asyncpg.Connection = Depends(get_db_conn)):
    return await get_anchors(conn)


@router.post("/anchors")
async def create_anchor(body: AnchorUpdate, request: Request,
                        _auth=Depends(auth_dependency),
                        conn: asyncpg.Connection = Depends(get_db_conn)):
    import uuid
    anchor_id = str(uuid.uuid4())
    anchor = {"id": anchor_id, **body.model_dump()}
    await upsert_anchor(conn, anchor)
    await sync_crontab(request.app.state.pool, request.state.user_id)
    await manager.broadcast({"type": "anchors_updated"}, request.state.user_id)
    return anchor


@router.put("/anchors/{anchor_id}")
async def update_anchor(anchor_id: str, body: AnchorUpdate, request: Request,
                        _auth=Depends(auth_dependency),
                        conn: asyncpg.Connection = Depends(get_db_conn)):
    anchor = {"id": anchor_id, **body.model_dump()}
    await upsert_anchor(conn, anchor)
    await sync_crontab(request.app.state.pool, request.state.user_id)
    await manager.broadcast({"type": "anchors_updated"}, request.state.user_id)
    return anchor


@router.delete("/anchors/{anchor_id}")
async def delete_anchor_route(anchor_id: str, request: Request,
                              _auth=Depends(auth_dependency),
                              conn: asyncpg.Connection = Depends(get_db_conn)):
    await delete_anchor(conn, anchor_id)
    await sync_crontab(request.app.state.pool, request.state.user_id)
    await manager.broadcast({"type": "anchors_updated"}, request.state.user_id)
    return {"ok": True}
