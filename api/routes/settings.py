from fastapi import APIRouter, Depends, Request
from pydantic import BaseModel
import asyncpg
from db.pg_queries import get_all_user_settings, set_user_setting
from db.pool_middleware import get_db_conn
from api.auth import auth_dependency

router = APIRouter()


class SetSettingBody(BaseModel):
    value: str


@router.get("/settings")
async def list_settings(request: Request, _auth=Depends(auth_dependency),
                        conn: asyncpg.Connection = Depends(get_db_conn)):
    return await get_all_user_settings(conn)


@router.put("/settings/{key}")
async def put_setting(key: str, body: SetSettingBody, request: Request,
                      _auth=Depends(auth_dependency),
                      conn: asyncpg.Connection = Depends(get_db_conn)):
    await set_user_setting(conn, request.state.user_id, key, body.value)
    return {"ok": True}
