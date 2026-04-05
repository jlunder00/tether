"""API routes for session status — shows active multi-turn sessions."""
from fastapi import APIRouter, Depends, Request

from api.auth import auth_dependency
from db.queries import get_db

router = APIRouter(prefix="/sessions", tags=["sessions"])


@router.get("")
async def get_active_sessions(request: Request, _auth=Depends(auth_dependency)):
    db = request.state.db_path
    with get_db(db) as conn:
        rows = conn.execute(
            "SELECT * FROM sessions WHERE state IN ('active', 'waiting_user') "
            "ORDER BY last_activity DESC"
        ).fetchall()
    return {"sessions": [dict(r) for r in rows]}
