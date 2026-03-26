from fastapi import APIRouter
from pathlib import Path
from db.queries import get_plan, upsert_tasks
import api.config as cfg

router = APIRouter()


@router.get("/plan/{date}")
async def get_plan_route(date: str):
    return get_plan(cfg.DB_PATH, date)


@router.put("/plan/{date}/anchors/{anchor_id}")
async def put_anchor_tasks(date: str, anchor_id: str, body: dict):
    upsert_tasks(cfg.DB_PATH, date, anchor_id,
                 tasks=body.get("tasks", []), notes=body.get("notes", ""))
    return {"ok": True}
