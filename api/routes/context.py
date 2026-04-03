from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel
from db.queries import (
    get_context_entries, upsert_context_entry, delete_context_entry,
    rename_context_subject,
)
from api.ws import manager
from api.auth import auth_dependency
import api.config as cfg

router = APIRouter()


@router.get("/context")
async def list_context(request: Request, _auth=Depends(auth_dependency), prefix: str = "", top_level_only: bool = False):
    return get_context_entries(request.state.db_path,
                               prefix=prefix or None,
                               top_level_only=top_level_only)


@router.get("/context/{subject:path}")
async def get_context(subject: str, request: Request, _auth=Depends(auth_dependency)):
    entries = get_context_entries(request.state.db_path, prefix=subject)
    match = next((e for e in entries if e["subject"] == subject), None)
    if not match:
        raise HTTPException(status_code=404, detail="Context entry not found")
    return match


@router.put("/context/{subject:path}")
async def put_context(subject: str, body: dict, request: Request, _auth=Depends(auth_dependency)):
    upsert_context_entry(request.state.db_path, subject, body.get("body", ""))
    await manager.broadcast({"type": "context_updated"}, request.state.user_id)
    return {"ok": True}


class RenameBody(BaseModel):
    new_subject: str


@router.post("/context/{subject:path}/rename")
async def rename_context(subject: str, body: RenameBody, request: Request, _auth=Depends(auth_dependency)):
    rename_context_subject(request.state.db_path, subject, body.new_subject)
    await manager.broadcast({"type": "context_updated"}, request.state.user_id)
    return {"ok": True}


@router.delete("/context/{subject:path}")
async def delete_context(subject: str, request: Request, _auth=Depends(auth_dependency)):
    delete_context_entry(request.state.db_path, subject)
    await manager.broadcast({"type": "context_updated"}, request.state.user_id)
    return {"ok": True}
