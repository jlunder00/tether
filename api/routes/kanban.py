import sqlite3
from fastapi import APIRouter, Depends, HTTPException, Request
from db.queries import (
    get_kanban_columns, create_kanban_column, update_kanban_column,
    delete_kanban_column, seed_kanban_columns,
)
from api.auth import auth_dependency

router = APIRouter()


@router.get("/kanban/columns")
async def list_columns(request: Request, _auth=Depends(auth_dependency)):
    try:
        seed_kanban_columns(request.state.db_path)
    except sqlite3.OperationalError:
        pass  # table may not exist yet on unmigrated DB
    return get_kanban_columns(request.state.db_path, user_id=request.state.user_id)


@router.post("/kanban/columns")
async def create_column(body: dict, request: Request, _auth=Depends(auth_dependency)):
    if "name" not in body:
        raise HTTPException(status_code=422, detail="'name' is required")
    return create_kanban_column(
        request.state.db_path,
        body["name"],
        body.get("position", 0),
        body.get("color"),
        body.get("match_rules", {}),
        body.get("entry_rules", {}),
        request.state.user_id,
    )


@router.patch("/kanban/columns/{column_id}")
async def patch_column(column_id: str, body: dict, request: Request, _auth=Depends(auth_dependency)):
    result = update_kanban_column(request.state.db_path, column_id, body)
    if result is None:
        raise HTTPException(status_code=404, detail="Column not found")
    return result


@router.delete("/kanban/columns/{column_id}")
async def remove_column(column_id: str, request: Request, _auth=Depends(auth_dependency)):
    delete_kanban_column(request.state.db_path, column_id)
    return {"ok": True}
