from fastapi import APIRouter, Depends, Request
from pydantic import BaseModel
from db.queries import get_all_user_settings, set_user_setting
from api.auth import auth_dependency

router = APIRouter()


class SetSettingBody(BaseModel):
    value: str


@router.get("/settings")
async def list_settings(
    request: Request,
    _auth=Depends(auth_dependency),
):
    """Return all user settings as a {key: value} dict."""
    return get_all_user_settings(request.state.db_path, request.state.user_id)


@router.put("/settings/{key}")
async def put_setting(
    key: str,
    body: SetSettingBody,
    request: Request,
    _auth=Depends(auth_dependency),
):
    """Create or update a single user setting."""
    set_user_setting(request.state.db_path, request.state.user_id, key, body.value)
    return {"ok": True}
