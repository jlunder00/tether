from fastapi import APIRouter, Depends, Request
from datetime import date as date_type, timedelta
from db.queries import get_plan, upsert_plan, upsert_tasks, list_plan_dates
from api.ws import manager
from api.auth import auth_dependency
import api.config as cfg

router = APIRouter()


@router.get("/plans")
async def list_plans(request: Request, _auth=Depends(auth_dependency)):
    return list_plan_dates(request.state.db_path)


@router.get("/plan/range")
async def get_plan_range(start: str, end: str, request: Request, _auth=Depends(auth_dependency)):
    start_d = date_type.fromisoformat(start)
    end_d = date_type.fromisoformat(end)
    result = {}
    d = start_d
    while d <= end_d:
        result[str(d)] = get_plan(request.state.db_path, str(d))
        d += timedelta(days=1)
    return result


@router.get("/plan/{date}")
async def get_plan_route(date: str, request: Request, _auth=Depends(auth_dependency)):
    return get_plan(request.state.db_path, date)


@router.put("/plan/{date}/anchors/{anchor_id}")
async def put_anchor_tasks(date: str, anchor_id: str, body: dict, request: Request, _auth=Depends(auth_dependency)):
    tasks_raw = body.get("tasks", [])
    tasks = [
        {"text": t, "status": "pending"} if isinstance(t, str) else t
        for t in tasks_raw
    ]
    upsert_plan(request.state.db_path, date)
    updated_tasks = upsert_tasks(request.state.db_path, date, anchor_id, tasks,
                                 notes=body.get("notes", ""))
    await manager.broadcast({"type": "plan_updated", "date": date, "anchor_id": anchor_id}, request.state.user_id)
    return {"ok": True, "tasks": updated_tasks}
