from fastapi import APIRouter, Depends, HTTPException, Request
import asyncpg
from db.pg_queries import (
    get_milestones, create_milestone, patch_milestone, delete_milestone,
    link_milestone_task, unlink_milestone_task,
)
from db.pool_middleware import get_db_conn
from api.routes._common import _validate_motif
from api.auth import auth_dependency

router = APIRouter()


@router.get("/milestones")
async def list_all_milestones(_auth=Depends(auth_dependency),
                              conn: asyncpg.Connection = Depends(get_db_conn)):
    return await get_milestones(conn)


@router.get("/context/{subject:path}/milestones")
async def list_milestones(subject: str, _auth=Depends(auth_dependency),
                          conn: asyncpg.Connection = Depends(get_db_conn)):
    return await get_milestones(conn, subject)


@router.post("/context/{subject:path}/milestones")
async def create_milestone_route(subject: str, body: dict,
                                 _auth=Depends(auth_dependency),
                                 conn: asyncpg.Connection = Depends(get_db_conn)):
    if "name" not in body:
        raise HTTPException(status_code=422, detail="'name' is required")
    _validate_motif(body)
    return await create_milestone(
        conn, subject, body["name"],
        description=body.get("description"),
        target_date=body.get("target_date"),
        color=body.get("color"),
        motif=body.get("motif", "anchor"),
    )


@router.patch("/milestones/{milestone_id}")
async def patch_milestone_route(milestone_id: str, body: dict,
                                _auth=Depends(auth_dependency),
                                conn: asyncpg.Connection = Depends(get_db_conn)):
    _validate_motif(body)
    result = await patch_milestone(conn, milestone_id, body)
    if result is None:
        raise HTTPException(status_code=404, detail="Milestone not found")
    return result


@router.delete("/milestones/{milestone_id}")
async def delete_milestone_route(milestone_id: str,
                                 _auth=Depends(auth_dependency),
                                 conn: asyncpg.Connection = Depends(get_db_conn)):
    await delete_milestone(conn, milestone_id)
    return {"ok": True}


@router.post("/milestones/{milestone_id}/tasks")
async def link_task(milestone_id: str, body: dict,
                    _auth=Depends(auth_dependency),
                    conn: asyncpg.Connection = Depends(get_db_conn)):
    if "task_id" not in body:
        raise HTTPException(status_code=422, detail="'task_id' is required")
    await link_milestone_task(conn, milestone_id, body["task_id"])
    return {"ok": True}


@router.delete("/milestones/{milestone_id}/tasks/{task_id}")
async def unlink_task(milestone_id: str, task_id: str,
                      _auth=Depends(auth_dependency),
                      conn: asyncpg.Connection = Depends(get_db_conn)):
    await unlink_milestone_task(conn, milestone_id, task_id)
    return {"ok": True}
