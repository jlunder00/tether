from fastapi import APIRouter, Depends, Request
from pydantic import BaseModel
from db.queries import get_anchors, upsert_anchor, delete_anchor
from bot.crontab import sync_crontab
from api.ws import manager
from api.auth import auth_dependency
import api.config as cfg

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
async def get_anchors_route(request: Request, _auth=Depends(auth_dependency)):
    return get_anchors(request.state.db_path)


@router.post("/anchors")
async def create_anchor(body: AnchorUpdate, request: Request, _auth=Depends(auth_dependency)):
    import uuid
    anchor_id = body.name.lower().replace(" ", "_") + "_" + uuid.uuid4().hex[:6]
    anchor = {"id": anchor_id, **body.model_dump()}
    upsert_anchor(request.state.db_path, anchor)
    sync_crontab(request.state.db_path)
    await manager.broadcast({"type": "anchors_updated"}, request.state.user_id)
    return anchor


@router.put("/anchors/{anchor_id}")
async def update_anchor(anchor_id: str, body: AnchorUpdate, request: Request, _auth=Depends(auth_dependency)):
    anchor = {"id": anchor_id, **body.model_dump()}
    upsert_anchor(request.state.db_path, anchor)
    sync_crontab(request.state.db_path)
    await manager.broadcast({"type": "anchors_updated"}, request.state.user_id)
    return anchor


@router.delete("/anchors/{anchor_id}")
async def delete_anchor_route(anchor_id: str, request: Request, _auth=Depends(auth_dependency)):
    delete_anchor(request.state.db_path, anchor_id)
    sync_crontab(request.state.db_path)
    await manager.broadcast({"type": "anchors_updated"}, request.state.user_id)
    return {"ok": True}
