"""API routes for session status — shows active multi-turn sessions."""
from fastapi import APIRouter, Depends
import asyncpg
from api.auth import auth_dependency
from db.pool_middleware import get_db_conn
from db.pg_queries.sessions import get_active_sessions

router = APIRouter(prefix="/sessions", tags=["sessions"])


@router.get("")
async def get_active_sessions_route(_auth=Depends(auth_dependency),
                                    conn: asyncpg.Connection = Depends(get_db_conn)):
    return {"sessions": await get_active_sessions(conn)}
