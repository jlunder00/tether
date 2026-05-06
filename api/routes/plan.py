from fastapi import APIRouter, Depends, Request
import asyncpg
from db.pg_queries import get_plan, upsert_plan, upsert_tasks, list_plan_dates
from db.pg_queries.plans import get_plans_for_range
from db.pool_middleware import get_db_conn
from api.ws import manager
from api.auth import auth_dependency

router = APIRouter()


@router.get("/plans")
async def list_plans(_auth=Depends(auth_dependency),
                     conn: asyncpg.Connection = Depends(get_db_conn)):
    return await list_plan_dates(conn)


@router.get("/plan/range")
async def get_plan_range(start: str, end: str, _auth=Depends(auth_dependency),
                         conn: asyncpg.Connection = Depends(get_db_conn)):
    return await get_plans_for_range(conn, start, end)


@router.get("/plan/{date}")
async def get_plan_route(date: str, _auth=Depends(auth_dependency),
                         conn: asyncpg.Connection = Depends(get_db_conn)):
    return await get_plan(conn, date)


@router.put("/plan/{date}/anchors/{anchor_id}")
async def put_anchor_tasks(date: str, anchor_id: str, body: dict,
                           request: Request, _auth=Depends(auth_dependency),
                           conn: asyncpg.Connection = Depends(get_db_conn)):
    tasks_raw = body.get("tasks", [])
    tasks = [
        {"text": t, "status": "pending"} if isinstance(t, str) else t
        for t in tasks_raw
    ]
    await upsert_plan(conn, date)
    updated_tasks = await upsert_tasks(conn, date, anchor_id, tasks,
                                       notes=body.get("notes", ""))
    await manager.broadcast({"type": "plan_updated", "date": date, "anchor_id": anchor_id},
                             request.state.user_id)
    return {"ok": True, "tasks": updated_tasks}
