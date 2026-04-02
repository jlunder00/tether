from fastapi import APIRouter, Depends, HTTPException, Request
from db.queries import patch_task_fields, move_task_atomic, \
    add_task_dependency, remove_task_dependency
from api.auth import auth_dependency
import api.config as cfg

router = APIRouter()


@router.patch("/tasks/{task_uuid}")
async def patch_task(task_uuid: str, body: dict, request: Request, _auth=Depends(auth_dependency)):
    result = patch_task_fields(request.state.db_path, task_uuid, body)
    if result is None:
        raise HTTPException(status_code=404, detail="Task not found")
    return result


@router.put("/tasks/{task_uuid}/move")
async def move_task(task_uuid: str, body: dict, request: Request, _auth=Depends(auth_dependency)):
    try:
        move_task_atomic(request.state.db_path, task_uuid,
                         body["date"], body["anchor_id"], body.get("position"))
    except ValueError as e:
        raise HTTPException(status_code=404, detail=str(e))
    return {"ok": True}


@router.post("/tasks/{task_uuid}/dependencies")
async def add_dependency(task_uuid: str, body: dict, request: Request, _auth=Depends(auth_dependency)):
    add_task_dependency(request.state.db_path, task_uuid, body["blocked_by_id"])
    return {"ok": True}


@router.delete("/tasks/{task_uuid}/dependencies/{blocked_by_id}")
async def remove_dependency(task_uuid: str, blocked_by_id: str, request: Request, _auth=Depends(auth_dependency)):
    remove_task_dependency(request.state.db_path, task_uuid, blocked_by_id)
    return {"ok": True}
