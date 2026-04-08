from fastapi import APIRouter, Depends, HTTPException, Request
from db.queries import (
    get_milestones, create_milestone, patch_milestone, delete_milestone,
    link_milestone_task, unlink_milestone_task,
)
from api.auth import auth_dependency
import api.config as cfg

router = APIRouter()


@router.get("/milestones")
async def list_all_milestones(request: Request, _auth=Depends(auth_dependency)):
    return get_milestones(request.state.db_path)


@router.get("/context/{subject:path}/milestones")
async def list_milestones(subject: str, request: Request, _auth=Depends(auth_dependency)):
    return get_milestones(request.state.db_path, subject)


@router.post("/context/{subject:path}/milestones")
async def create_milestone_route(subject: str, body: dict, request: Request, _auth=Depends(auth_dependency)):
    if "name" not in body:
        raise HTTPException(status_code=422, detail="'name' is required")
    return create_milestone(
        request.state.db_path, subject, body["name"],
        description=body.get("description"),
        target_date=body.get("target_date"),
        color=body.get("color"),
    )


@router.patch("/milestones/{milestone_id}")
async def patch_milestone_route(milestone_id: str, body: dict, request: Request, _auth=Depends(auth_dependency)):
    result = patch_milestone(request.state.db_path, milestone_id, body)
    if result is None:
        raise HTTPException(status_code=404, detail="Milestone not found")
    return result


@router.delete("/milestones/{milestone_id}")
async def delete_milestone_route(milestone_id: str, request: Request, _auth=Depends(auth_dependency)):
    delete_milestone(request.state.db_path, milestone_id)
    return {"ok": True}


@router.post("/milestones/{milestone_id}/tasks")
async def link_task(milestone_id: str, body: dict, request: Request, _auth=Depends(auth_dependency)):
    if "task_id" not in body:
        raise HTTPException(status_code=422, detail="'task_id' is required")
    link_milestone_task(request.state.db_path, milestone_id, body["task_id"])
    return {"ok": True}


@router.delete("/milestones/{milestone_id}/tasks/{task_id}")
async def unlink_task(milestone_id: str, task_id: str, request: Request, _auth=Depends(auth_dependency)):
    unlink_milestone_task(request.state.db_path, milestone_id, task_id)
    return {"ok": True}
