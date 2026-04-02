from fastapi import APIRouter, Depends, Request
from pydantic import BaseModel
from db.queries import get_anchors, upsert_anchor
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


@router.put("/anchors/{anchor_id}")
async def update_anchor(anchor_id: str, body: AnchorUpdate, request: Request, _auth=Depends(auth_dependency)):
    anchor = {"id": anchor_id, **body.model_dump()}
    upsert_anchor(request.state.db_path, anchor)
    sync_crontab(request.state.db_path)
    await manager.broadcast({"type": "anchors_updated"}, request.state.user_id)
    return anchor
