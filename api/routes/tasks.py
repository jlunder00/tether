from fastapi import APIRouter, HTTPException
from db.queries import patch_task_fields, move_task_atomic, \
    add_task_dependency, remove_task_dependency
import api.config as cfg

router = APIRouter()


@router.patch("/tasks/{task_uuid}")
async def patch_task(task_uuid: str, body: dict):
    result = patch_task_fields(cfg.DB_PATH, task_uuid, body)
    if result is None:
        raise HTTPException(status_code=404, detail="Task not found")
    return result


@router.put("/tasks/{task_uuid}/move")
async def move_task(task_uuid: str, body: dict):
    try:
        move_task_atomic(cfg.DB_PATH, task_uuid,
                         body["date"], body["anchor_id"], body.get("position"))
    except ValueError as e:
        raise HTTPException(status_code=404, detail=str(e))
    return {"ok": True}


@router.post("/tasks/{task_uuid}/dependencies")
async def add_dependency(task_uuid: str, body: dict):
    add_task_dependency(cfg.DB_PATH, task_uuid, body["blocked_by_id"])
    return {"ok": True}


@router.delete("/tasks/{task_uuid}/dependencies/{blocked_by_id}")
async def remove_dependency(task_uuid: str, blocked_by_id: str):
    remove_task_dependency(cfg.DB_PATH, task_uuid, blocked_by_id)
    return {"ok": True}
