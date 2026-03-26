from fastapi import APIRouter
from db.queries import get_context_entries, upsert_context_entry, delete_context_entry
from api.ws import manager
import api.config as cfg

router = APIRouter()


@router.get("/context")
async def list_context():
    return get_context_entries(cfg.DB_PATH)


@router.put("/context/{subject}")
async def put_context(subject: str, body: dict):
    upsert_context_entry(cfg.DB_PATH, subject, body.get("body", ""))
    await manager.broadcast({"type": "context_updated"})
    return {"ok": True}


@router.delete("/context/{subject}")
async def delete_context(subject: str):
    delete_context_entry(cfg.DB_PATH, subject)
    await manager.broadcast({"type": "context_updated"})
    return {"ok": True}
