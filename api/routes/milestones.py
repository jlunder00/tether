from fastapi import APIRouter, HTTPException
from db.queries import (
    get_milestones, create_milestone, patch_milestone, delete_milestone,
    link_milestone_task, unlink_milestone_task,
)
import api.config as cfg

router = APIRouter()


@router.get("/milestones")
async def list_all_milestones():
    return get_milestones(cfg.DB_PATH)


@router.get("/context/{subject:path}/milestones")
async def list_milestones(subject: str):
    return get_milestones(cfg.DB_PATH, subject)


@router.post("/context/{subject:path}/milestones")
async def create_milestone_route(subject: str, body: dict):
    return create_milestone(
        cfg.DB_PATH, subject, body["name"],
        description=body.get("description"),
        target_date=body.get("target_date"),
    )


@router.patch("/milestones/{milestone_id}")
async def patch_milestone_route(milestone_id: str, body: dict):
    result = patch_milestone(cfg.DB_PATH, milestone_id, body)
    if result is None:
        raise HTTPException(status_code=404, detail="Milestone not found")
    return result


@router.delete("/milestones/{milestone_id}")
async def delete_milestone_route(milestone_id: str):
    delete_milestone(cfg.DB_PATH, milestone_id)
    return {"ok": True}


@router.post("/milestones/{milestone_id}/tasks")
async def link_task(milestone_id: str, body: dict):
    link_milestone_task(cfg.DB_PATH, milestone_id, body["task_id"])
    return {"ok": True}


@router.delete("/milestones/{milestone_id}/tasks/{task_id}")
async def unlink_task(milestone_id: str, task_id: str):
    unlink_milestone_task(cfg.DB_PATH, milestone_id, task_id)
    return {"ok": True}
