from pydantic import BaseModel
from fastapi import APIRouter, Depends, Request
from db.pool_middleware import get_db_conn
from db.pg_queries.preferences import upsert_user_preference, get_user_preferences
from api.auth import auth_dependency

router = APIRouter(prefix="/user/preferences", tags=["preferences"])
# NOTE: This router is included with prefix="/api" in main.py → final paths are /api/user/preferences


class PreferencesBody(BaseModel):
    theme: str | None = None
    mode: str | None = None


@router.get("")
async def get_preferences(request: Request, _auth=Depends(auth_dependency), conn=Depends(get_db_conn)):
    user_id = request.state.user_id
    prefs = await get_user_preferences(conn, user_id)
    return {"theme": prefs.get("theme"), "mode": prefs.get("mode")}


@router.patch("")
async def patch_preferences(body: PreferencesBody, request: Request, _auth=Depends(auth_dependency), conn=Depends(get_db_conn)):
    user_id = request.state.user_id
    if body.theme is not None:
        await upsert_user_preference(conn, user_id, "theme", body.theme)
    if body.mode is not None:
        await upsert_user_preference(conn, user_id, "mode", body.mode)
    return {"ok": True}
