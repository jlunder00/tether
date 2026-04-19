from fastapi import APIRouter, Depends, HTTPException, Request
import asyncpg
from db.pg_queries import (
    get_kanban_columns, create_kanban_column, update_kanban_column,
    delete_kanban_column, seed_kanban_columns, migrate_backlog_column,
)
from db.pool_middleware import get_db_conn
from api.auth import auth_dependency

router = APIRouter()


@router.get("/kanban/columns")
async def list_columns(_auth=Depends(auth_dependency),
                       conn: asyncpg.Connection = Depends(get_db_conn)):
    await seed_kanban_columns(conn)
    await migrate_backlog_column(conn)
    return await get_kanban_columns(conn)


@router.post("/kanban/columns")
async def create_column(body: dict, _auth=Depends(auth_dependency),
                        conn: asyncpg.Connection = Depends(get_db_conn)):
    if "name" not in body:
        raise HTTPException(status_code=422, detail="'name' is required")
    return await create_kanban_column(
        conn,
        body["name"],
        body.get("position", 0),
        body.get("color"),
        body.get("match_rules", {}),
        body.get("entry_rules", {}),
    )


@router.patch("/kanban/columns/{column_id}")
async def patch_column(column_id: str, body: dict,
                       _auth=Depends(auth_dependency),
                       conn: asyncpg.Connection = Depends(get_db_conn)):
    result = await update_kanban_column(conn, column_id, body)
    if result is None:
        raise HTTPException(status_code=404, detail="Column not found")
    return result


@router.delete("/kanban/columns/{column_id}")
async def remove_column(column_id: str, _auth=Depends(auth_dependency),
                        conn: asyncpg.Connection = Depends(get_db_conn)):
    await delete_kanban_column(conn, column_id)
    return {"ok": True}
