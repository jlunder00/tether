from fastapi import APIRouter
from db.queries import get_anchors
import api.config as cfg

router = APIRouter()


@router.get("/anchors")
async def get_anchors_route():
    return get_anchors(cfg.DB_PATH)
