from __future__ import annotations
from typing import Literal
from pydantic import BaseModel
from fastapi import APIRouter, Depends, HTTPException, Request
from db.pool_middleware import get_db_conn
from db.pg_queries.preferences import upsert_user_preference, get_user_preferences
from db.pg_queries.notifications import (
    get_notification_routing_with_defaults,
    set_notification_routing,
)
from api.auth import auth_dependency

router = APIRouter(prefix="/user/preferences", tags=["preferences"])
# NOTE: This router is included with prefix="/api" in main.py → final paths are /api/user/preferences

# ---------------------------------------------------------------------------
# Notification routing validation types
# ---------------------------------------------------------------------------

_VALID_NOTIFICATION_TYPES = Literal[
    "anchor_ping", "task_followup", "beacon", "meeting_event", "scheduling_update"
]
_RoutingMode = Literal["thread_by_key", "fixed", "bot_decides", "new_each"]
_RoutingPriority = Literal["normal", "important", "urgent"]
_RoutingChannel = Literal["telegram", "web", "discord", "slack"]


class NotificationRoutingEntry(BaseModel):
    mode: _RoutingMode
    priority: _RoutingPriority
    external: list[_RoutingChannel]
    key_template: str | None = None       # only relevant for thread_by_key mode
    conversation_id: str | None = None    # only relevant for fixed mode


# Pydantic enforces that only these 5 keys appear in the dict.
NotificationRouting = dict[_VALID_NOTIFICATION_TYPES, NotificationRoutingEntry]


# ---------------------------------------------------------------------------
# Request / response models
# ---------------------------------------------------------------------------

class PreferencesBody(BaseModel):
    theme: str | None = None
    mode: str | None = None
    notification_routing: NotificationRouting | None = None


# ---------------------------------------------------------------------------
# Routes
# ---------------------------------------------------------------------------

@router.get("")
async def get_preferences(
    request: Request,
    _auth=Depends(auth_dependency),
    conn=Depends(get_db_conn),
):
    user_id = request.state.user_id
    prefs = await get_user_preferences(conn, user_id)
    routing = await get_notification_routing_with_defaults(conn, user_id)
    return {
        "theme": prefs.get("theme"),
        "mode": prefs.get("mode"),
        "notification_routing": routing,
    }


@router.patch("")
async def patch_preferences(
    body: PreferencesBody,
    request: Request,
    _auth=Depends(auth_dependency),
    conn=Depends(get_db_conn),
):
    if body.theme is None and body.mode is None and body.notification_routing is None:
        raise HTTPException(
            status_code=400,
            detail="At least one field (theme, mode, notification_routing) must be provided",
        )
    user_id = request.state.user_id
    if body.theme is not None:
        await upsert_user_preference(conn, user_id, "theme", body.theme)
    if body.mode is not None:
        await upsert_user_preference(conn, user_id, "mode", body.mode)
    if body.notification_routing is not None:
        # Serialize validated Pydantic models back to plain dicts for storage.
        routing_dict = {
            k: v.model_dump(exclude_none=True)
            for k, v in body.notification_routing.items()
        }
        await set_notification_routing(conn, user_id, routing_dict)
    return {"ok": True}
