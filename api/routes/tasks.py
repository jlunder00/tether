from fastapi import APIRouter, Depends, HTTPException, Request
import asyncpg
from db.pg_queries import (
    patch_task_fields, move_task_atomic,
    add_task_dependency, remove_task_dependency,
    get_subtasks, create_subtask, update_subtask, delete_subtask, reorder_subtasks,
    search_entities,
    get_unscheduled_tasks, create_unscheduled_task, get_task_by_uuid, get_all_tasks,
    link_milestone_task, upsert_plan, delete_task_by_uuid, get_full_task_dependencies,
)
from db.pool_middleware import get_db_conn
from api.auth import auth_dependency

router = APIRouter()


@router.get("/search")
async def search(q: str = "", type: str = "all",
                 _auth=Depends(auth_dependency),
                 conn: asyncpg.Connection = Depends(get_db_conn)):
    if not q.strip():
        return []
    return await search_entities(conn, q.strip(), type)


# --- Literal path routes MUST come before {task_uuid} parameterized routes ---

@router.get("/tasks/all")
async def list_all_tasks(_auth=Depends(auth_dependency),
                         conn: asyncpg.Connection = Depends(get_db_conn)):
    return await get_all_tasks(conn)


@router.get("/tasks/unscheduled")
async def list_unscheduled(_auth=Depends(auth_dependency),
                           conn: asyncpg.Connection = Depends(get_db_conn)):
    return await get_unscheduled_tasks(conn)


@router.post("/tasks/unscheduled")
async def create_unscheduled(body: dict, request: Request,
                             _auth=Depends(auth_dependency),
                             conn: asyncpg.Connection = Depends(get_db_conn)):
    if "text" not in body:
        raise HTTPException(status_code=422, detail="'text' is required")
    milestone_id = body.get("milestone_id")
    date = body.get("date")
    anchor_id = body.get("anchor_id")
    async with conn.transaction():
        task = await create_unscheduled_task(
            conn, body["text"],
            description=body.get("description"),
            status=body.get("status", "pending"),
            context_subject=body.get("context_subject"),
        )
        if milestone_id:
            await link_milestone_task(conn, milestone_id, task["id"])
        if date and anchor_id:
            await upsert_plan(conn, date)
            await move_task_atomic(conn, task["id"], date, anchor_id)
    return await get_task_by_uuid(conn, task["id"])


# --- Parameterized routes below ---

@router.get("/tasks/{task_uuid}")
async def get_task(task_uuid: str, _auth=Depends(auth_dependency),
                   conn: asyncpg.Connection = Depends(get_db_conn)):
    task = await get_task_by_uuid(conn, task_uuid)
    if task is None:
        raise HTTPException(status_code=404, detail="Task not found")
    return task


@router.patch("/tasks/{task_uuid}")
async def patch_task(task_uuid: str, body: dict,
                     _auth=Depends(auth_dependency),
                     conn: asyncpg.Connection = Depends(get_db_conn)):
    async with conn.transaction():
        result = await patch_task_fields(conn, task_uuid, body)
    if result is None:
        raise HTTPException(status_code=404, detail="Task not found")
    return result


@router.delete("/tasks/{task_uuid}")
async def delete_task(task_uuid: str, _auth=Depends(auth_dependency),
                      conn: asyncpg.Connection = Depends(get_db_conn)):
    async with conn.transaction():
        await delete_task_by_uuid(conn, task_uuid)
    return {"ok": True}


@router.put("/tasks/{task_uuid}/move")
async def move_task(task_uuid: str, body: dict,
                    _auth=Depends(auth_dependency),
                    conn: asyncpg.Connection = Depends(get_db_conn)):
    try:
        await move_task_atomic(conn, task_uuid,
                               body.get("date"), body.get("anchor_id"), body.get("position"))
    except ValueError as e:
        raise HTTPException(status_code=404, detail=str(e))
    return {"ok": True}


@router.get("/tasks/{task_uuid}/dependencies")
async def task_dependencies(task_uuid: str, _auth=Depends(auth_dependency),
                            conn: asyncpg.Connection = Depends(get_db_conn)):
    return await get_full_task_dependencies(conn, task_uuid)


@router.post("/tasks/{task_uuid}/dependencies")
async def add_dependency_route(task_uuid: str, body: dict,
                               _auth=Depends(auth_dependency),
                               conn: asyncpg.Connection = Depends(get_db_conn)):
    await add_task_dependency(conn, task_uuid, body["blocked_by_id"])
    return {"ok": True}


@router.delete("/tasks/{task_uuid}/dependencies/{blocked_by_id}")
async def remove_dependency_route(task_uuid: str, blocked_by_id: str,
                                  _auth=Depends(auth_dependency),
                                  conn: asyncpg.Connection = Depends(get_db_conn)):
    await remove_task_dependency(conn, task_uuid, blocked_by_id)
    return {"ok": True}


@router.get("/tasks/{task_uuid}/subtasks")
async def get_task_subtasks(task_uuid: str, _auth=Depends(auth_dependency),
                            conn: asyncpg.Connection = Depends(get_db_conn)):
    return await get_subtasks(conn, task_uuid)


@router.post("/tasks/{task_uuid}/subtasks")
async def create_task_subtask(task_uuid: str, body: dict,
                              _auth=Depends(auth_dependency),
                              conn: asyncpg.Connection = Depends(get_db_conn)):
    return await create_subtask(conn, task_uuid, body["text"], body.get("position", 0))


@router.patch("/tasks/{task_uuid}/subtasks/{subtask_id}")
async def update_task_subtask(task_uuid: str, subtask_id: int, body: dict,
                              _auth=Depends(auth_dependency),
                              conn: asyncpg.Connection = Depends(get_db_conn)):
    await update_subtask(conn, subtask_id, **body)
    return {"ok": True}


@router.delete("/tasks/{task_uuid}/subtasks/{subtask_id}")
async def delete_task_subtask(task_uuid: str, subtask_id: int,
                              _auth=Depends(auth_dependency),
                              conn: asyncpg.Connection = Depends(get_db_conn)):
    await delete_subtask(conn, subtask_id)
    return {"ok": True}


@router.put("/tasks/{task_uuid}/subtasks/reorder")
async def reorder_task_subtasks(task_uuid: str, body: dict,
                                _auth=Depends(auth_dependency),
                                conn: asyncpg.Connection = Depends(get_db_conn)):
    await reorder_subtasks(conn, task_uuid, body["id_order"])
    return {"ok": True}


# Task-context linking (single context_subject model)
@router.get("/tasks/{task_uuid}/contexts")
async def get_task_context_links(task_uuid: str, _auth=Depends(auth_dependency),
                                 conn: asyncpg.Connection = Depends(get_db_conn)):
    task = await get_task_by_uuid(conn, task_uuid)
    if task is None:
        raise HTTPException(status_code=404, detail="Task not found")
    ctx = task.get("context_subject")
    return [ctx] if ctx else []


@router.post("/tasks/{task_uuid}/contexts")
async def link_task_to_context(task_uuid: str, body: dict,
                               _auth=Depends(auth_dependency),
                               conn: asyncpg.Connection = Depends(get_db_conn)):
    result = await patch_task_fields(conn, task_uuid, {"context_subject": body["subject"]})
    if result is None:
        raise HTTPException(status_code=404, detail="Task not found")
    return {"ok": True}


@router.delete("/tasks/{task_uuid}/contexts/{subject:path}")
async def unlink_task_from_context(task_uuid: str, subject: str,
                                   _auth=Depends(auth_dependency),
                                   conn: asyncpg.Connection = Depends(get_db_conn)):
    result = await patch_task_fields(conn, task_uuid, {"context_subject": None})
    if result is None:
        raise HTTPException(status_code=404, detail="Task not found")
    return {"ok": True}
