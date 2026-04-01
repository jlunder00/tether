from fastapi import APIRouter
from pydantic import BaseModel
from db.queries import get_anchors, upsert_anchor
from bot.crontab import sync_crontab
from api.ws import manager
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
async def get_anchors_route():
    return get_anchors(cfg.DB_PATH)


@router.put("/anchors/{anchor_id}")
async def update_anchor(anchor_id: str, body: AnchorUpdate):
    anchor = {"id": anchor_id, **body.model_dump()}
    upsert_anchor(cfg.DB_PATH, anchor)
    sync_crontab(cfg.DB_PATH)
    await manager.broadcast({"type": "anchors_updated"})
    return anchor
