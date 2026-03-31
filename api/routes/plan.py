from fastapi import APIRouter
from datetime import date as date_type, timedelta
from db.queries import get_plan, upsert_plan, upsert_tasks, list_plan_dates
from api.ws import manager
import api.config as cfg

router = APIRouter()


@router.get("/plans")
async def list_plans():
    return list_plan_dates(cfg.DB_PATH)


@router.get("/plan/range")
async def get_plan_range(start: str, end: str):
    start_d = date_type.fromisoformat(start)
    end_d = date_type.fromisoformat(end)
    result = {}
    d = start_d
    while d <= end_d:
        result[str(d)] = get_plan(cfg.DB_PATH, str(d))
        d += timedelta(days=1)
    return result


@router.get("/plan/{date}")
async def get_plan_route(date: str):
    return get_plan(cfg.DB_PATH, date)


@router.put("/plan/{date}/anchors/{anchor_id}")
async def put_anchor_tasks(date: str, anchor_id: str, body: dict):
    tasks_raw = body.get("tasks", [])
    tasks = [
        {"text": t, "status": "pending"} if isinstance(t, str) else t
        for t in tasks_raw
    ]
    upsert_plan(cfg.DB_PATH, date)
    updated_tasks = upsert_tasks(cfg.DB_PATH, date, anchor_id, tasks,
                                 notes=body.get("notes", ""))
    await manager.broadcast({"type": "plan_updated", "date": date, "anchor_id": anchor_id})
    return {"ok": True, "tasks": updated_tasks}
