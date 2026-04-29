from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel
import asyncpg
from db.pg_queries import (
    get_context_entries, upsert_context_entry, delete_context_entry,
    rename_context_subject,
)
from db.pool_middleware import get_db_conn
from db.pg_queries._motif import VALID_MOTIFS
from api.ws import manager
from api.auth import auth_dependency

router = APIRouter()


@router.get("/context")
async def list_context(_auth=Depends(auth_dependency),
                       conn: asyncpg.Connection = Depends(get_db_conn),
                       prefix: str = "", top_level_only: bool = False):
    return await get_context_entries(conn, prefix=prefix or None,
                                     top_level_only=top_level_only)


@router.get("/context/{subject:path}")
async def get_context(subject: str, _auth=Depends(auth_dependency),
                      conn: asyncpg.Connection = Depends(get_db_conn)):
    entries = await get_context_entries(conn, prefix=subject)
    match = next((e for e in entries if e["subject"] == subject), None)
    if not match:
        raise HTTPException(status_code=404, detail="Context entry not found")
    return match


@router.put("/context/{subject:path}")
async def put_context(subject: str, body: dict, request: Request,
                      _auth=Depends(auth_dependency),
                      conn: asyncpg.Connection = Depends(get_db_conn)):
    motif = body.get("motif")
    if motif is not None and motif not in VALID_MOTIFS:
        raise HTTPException(
            status_code=422,
            detail=f"Invalid motif: {motif!r}. Must be one of {sorted(VALID_MOTIFS)}",
        )
    await upsert_context_entry(conn, subject, body.get("body", ""), motif=motif)
    await manager.broadcast({"type": "context_updated"}, request.state.user_id)
    return {"ok": True}


class RenameBody(BaseModel):
    new_subject: str


@router.post("/context/{subject:path}/rename")
async def rename_context(subject: str, body: RenameBody, request: Request,
                         _auth=Depends(auth_dependency),
                         conn: asyncpg.Connection = Depends(get_db_conn)):
    await rename_context_subject(conn, subject, body.new_subject)
    await manager.broadcast({"type": "context_updated"}, request.state.user_id)
    return {"ok": True}


@router.delete("/context/{subject:path}")
async def delete_context(subject: str, request: Request,
                         _auth=Depends(auth_dependency),
                         conn: asyncpg.Connection = Depends(get_db_conn)):
    await delete_context_entry(conn, subject)
    await manager.broadcast({"type": "context_updated"}, request.state.user_id)
    return {"ok": True}
