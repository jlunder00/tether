"""API routes for session status — shows active multi-turn sessions."""
from fastapi import APIRouter, Depends
import asyncpg
from api.auth import auth_dependency
from db.pool_middleware import get_db_conn

router = APIRouter(prefix="/sessions", tags=["sessions"])


@router.get("")
async def get_active_sessions(_auth=Depends(auth_dependency),
                              conn: asyncpg.Connection = Depends(get_db_conn)):
    rows = await conn.fetch(
        "SELECT * FROM sessions WHERE state IN ('active', 'waiting_user') "
        "ORDER BY last_activity DESC"
    )
    return {"sessions": [dict(r) for r in rows]}
