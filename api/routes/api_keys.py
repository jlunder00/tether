from __future__ import annotations

import uuid

from fastapi import APIRouter, Depends, Request
from pydantic import BaseModel, Field
import asyncpg

from api.auth import auth_dependency
from db.pool_middleware import get_db_conn
import db.pg_queries.api_keys as key_queries

router = APIRouter()


class CreateKeyBody(BaseModel):
    name: str = Field(..., min_length=1, max_length=100)


@router.post("/keys", status_code=201)
async def create_key(
    body: CreateKeyBody,
    request: Request,
    _auth=Depends(auth_dependency),
    conn: asyncpg.Connection = Depends(get_db_conn),
):
    """Create a new API key. Returns the raw key once — it cannot be retrieved again."""
    raw_key, record = await key_queries.create_key(conn, request.state.user_id, body.name)
    return {**record, "raw_key": raw_key}


@router.get("/keys")
async def list_keys(
    request: Request,
    _auth=Depends(auth_dependency),
    conn: asyncpg.Connection = Depends(get_db_conn),
):
    return await key_queries.list_keys(conn, request.state.user_id)


@router.delete("/keys/{key_id}")
async def revoke_key(
    key_id: uuid.UUID,
    request: Request,
    _auth=Depends(auth_dependency),
    conn: asyncpg.Connection = Depends(get_db_conn),
):
    await key_queries.revoke_key(conn, str(key_id), request.state.user_id)
    return {"ok": True}
