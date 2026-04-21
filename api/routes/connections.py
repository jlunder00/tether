"""Connection management endpoints."""
from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
import asyncpg

from api.auth import auth_dependency
from db.pool_middleware import get_db_conn
from db.pg_auth_queries import get_user_by_username
from db.pg_queries.scheduling import (
    create_connection,
    get_connection,
    accept_connection,
    decline_connection,
    list_connections_for_user,
    patch_connection,
)

router = APIRouter()


class ConnectionRequestBody(BaseModel):
    target_username: str


class DeclineBody(BaseModel):
    block: bool = False


class PatchConnectionBody(BaseModel):
    auto_schedule: bool


@router.post("/connections/request", status_code=201)
async def request_connection(
    body: ConnectionRequestBody,
    auth=Depends(auth_dependency),
    conn: asyncpg.Connection = Depends(get_db_conn),
):
    caller_id = auth["user_id"]
    target = await get_user_by_username(conn, body.target_username)
    if not target:
        raise HTTPException(status_code=404, detail="User not found")
    try:
        result = await create_connection(conn, caller_id, target["id"], caller_id)
    except asyncpg.UniqueViolationError:
        raise HTTPException(status_code=409, detail="Connection already exists")
    return result


@router.post("/connections/{conn_id}/accept")
async def accept_connection_route(
    conn_id: int,
    auth=Depends(auth_dependency),
    conn: asyncpg.Connection = Depends(get_db_conn),
):
    caller_id = auth["user_id"]
    connection = await get_connection(conn, conn_id)
    if not connection:
        raise HTTPException(status_code=404, detail="Connection not found")
    if caller_id == connection["initiated_by"]:
        raise HTTPException(status_code=403, detail="Initiator cannot accept their own request")
    result = await accept_connection(conn, conn_id)
    return {"id": result["id"], "status": result["status"]}


@router.post("/connections/{conn_id}/decline")
async def decline_connection_route(
    conn_id: int,
    body: DeclineBody,
    auth=Depends(auth_dependency),
    conn: asyncpg.Connection = Depends(get_db_conn),
):
    caller_id = auth["user_id"]
    connection = await get_connection(conn, conn_id)
    if not connection:
        raise HTTPException(status_code=404, detail="Connection not found")
    if caller_id == connection["initiated_by"]:
        raise HTTPException(status_code=403, detail="Initiator cannot decline their own request")
    result = await decline_connection(conn, conn_id, block=body.block)
    if result is None:
        return {"id": conn_id, "deleted": True}
    return {"id": result["id"], "status": result["status"]}


@router.get("/connections")
async def list_connections(
    auth=Depends(auth_dependency),
    conn: asyncpg.Connection = Depends(get_db_conn),
):
    caller_id = auth["user_id"]
    return await list_connections_for_user(conn, caller_id)


@router.patch("/connections/{conn_id}")
async def patch_connection_route(
    conn_id: int,
    body: PatchConnectionBody,
    auth=Depends(auth_dependency),
    conn: asyncpg.Connection = Depends(get_db_conn),
):
    caller_id = auth["user_id"]
    connection = await get_connection(conn, conn_id)
    if not connection:
        raise HTTPException(status_code=404, detail="Connection not found")
    if caller_id not in (connection["user_a"], connection["user_b"]):
        raise HTTPException(status_code=403, detail="Not a participant")
    result = await patch_connection(conn, conn_id, body.auto_schedule)
    return result
