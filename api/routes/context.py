from fastapi import APIRouter, HTTPException
from pydantic import BaseModel
from db.queries import (
    get_context_entries, upsert_context_entry, delete_context_entry,
    rename_context_subject,
)
from api.ws import manager
import api.config as cfg

router = APIRouter()


@router.get("/context")
async def list_context(prefix: str = "", top_level_only: bool = False):
    return get_context_entries(cfg.DB_PATH,
                               prefix=prefix or None,
                               top_level_only=top_level_only)


@router.get("/context/{subject:path}")
async def get_context(subject: str):
    entries = get_context_entries(cfg.DB_PATH, prefix=subject)
    match = next((e for e in entries if e["subject"] == subject), None)
    if not match:
        raise HTTPException(status_code=404, detail="Context entry not found")
    return match


@router.put("/context/{subject:path}")
async def put_context(subject: str, body: dict):
    upsert_context_entry(cfg.DB_PATH, subject, body.get("body", ""))
    await manager.broadcast({"type": "context_updated"})
    return {"ok": True}


class RenameBody(BaseModel):
    new_subject: str


@router.post("/context/{subject:path}/rename")
async def rename_context(subject: str, body: RenameBody):
    rename_context_subject(cfg.DB_PATH, subject, body.new_subject)
    await manager.broadcast({"type": "context_updated"})
    return {"ok": True}


@router.delete("/context/{subject:path}")
async def delete_context(subject: str):
    delete_context_entry(cfg.DB_PATH, subject)
    await manager.broadcast({"type": "context_updated"})
    return {"ok": True}
