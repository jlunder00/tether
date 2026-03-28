from fastapi import APIRouter
from db.queries import get_plan, upsert_plan, upsert_tasks, list_plan_dates
from api.ws import manager
import api.config as cfg

router = APIRouter()


@router.get("/plans")
async def list_plans():
    return list_plan_dates(cfg.DB_PATH)


@router.get("/plan/{date}")
async def get_plan_route(date: str):
    return get_plan(cfg.DB_PATH, date)


@router.put("/plan/{date}/anchors/{anchor_id}")
async def put_anchor_tasks(date: str, anchor_id: str, body: dict):
    upsert_plan(cfg.DB_PATH, date)
    upsert_tasks(cfg.DB_PATH, date, anchor_id,
                 tasks=body.get("tasks", []), notes=body.get("notes", ""))
    await manager.broadcast({"type": "plan_updated", "date": date, "anchor_id": anchor_id})
    return {"ok": True}
