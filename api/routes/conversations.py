"""API routes — Conversations (Phase G).

Endpoints:
  GET    /conversations                   list conversations (RLS-scoped)
  POST   /conversations                   create conversation
  GET    /conversations/{id}              get single conversation
  PATCH  /conversations/{id}              patch conversation
  GET    /conversations/{id}/messages     list messages (before_id cursor paginated)
  PUT    /preferences/notifications       upsert notification routing prefs
  GET    /preferences/notifications       get notification routing prefs
  GET    /context-nodes/{id}/summary      get context node summary field

Note on before_id cursor pagination (messages endpoint): the cursor is the
integer primary key of conversation_history. This gives stable pages under
concurrent inserts, unlike offset-based pagination. The tradeoff is that
clients must treat the cursor as an opaque integer string. See PR description.
"""
from __future__ import annotations

import json
from typing import Literal

from fastapi import APIRouter, Depends, HTTPException, Query, Request
from pydantic import BaseModel

from api.auth import auth_dependency
from db.pg_queries.conversations import (
    create_conversation,
    get_conversation,
    list_conversations,
    list_conversation_messages,
    update_conversation,
)
from db.pg_queries.nodes import get_node
from db.pg_queries.preferences import get_user_preferences, upsert_user_preference
from db.pool_middleware import get_db_conn

router = APIRouter(tags=["conversations"])


# ---------------------------------------------------------------------------
# Pydantic models
# ---------------------------------------------------------------------------

_NOTIF_MODES = {"all", "focus", "quiet", "off"}
_CHANNELS = {"telegram", "email", "push"}

# Valid conversation states — open/closed existed from Phase B; pending/rejected
# added in Phase 3 for Beacon-initiated conversations (spec §7.1).
ConversationState = Literal["open", "closed", "pending", "rejected"]


class ConversationCreate(BaseModel):
    name: str
    priority: str = "normal"
    context_node_id: str | None = None
    thread_key: str | None = None


class ConversationPatch(BaseModel):
    name: str | None = None
    priority: str | None = None
    state: ConversationState | None = None
    context_node_id: str | None = None


class NotificationPrefsBody(BaseModel):
    mode: str | None = None
    priority_threshold: str | None = None
    channels: list[str] | None = None


# ---------------------------------------------------------------------------
# Helper: resolve folder_name for a single conversation dict
#
# Only used by single-item endpoints (POST/GET/PATCH) where get_conversation()
# does not JOIN context_nodes. The list endpoint already gets folder_name from
# the LEFT JOIN inside list_conversations(), so it doesn't need this.
# ---------------------------------------------------------------------------


async def _attach_folder_name(conn, conv: dict) -> dict:
    """Add folder_name to a single conversation dict via get_node lookup."""
    node_id = conv.get("context_node_id")
    node = await get_node(conn, node_id) if node_id else None
    conv["folder_name"] = node["name"] if node else None
    return conv


# ---------------------------------------------------------------------------
# GET /conversations
# ---------------------------------------------------------------------------


@router.get("/conversations")
async def list_convs(
    request: Request,
    state: str | None = Query(None),
    context_node_id: str | None = Query(None),
    limit: int = Query(50, ge=1, le=200),
    offset: int = Query(0, ge=0),
    _auth=Depends(auth_dependency),
    conn=Depends(get_db_conn),
):
    # list_conversations() already LEFT JOINs context_nodes for folder_name,
    # so no _attach_folder_name pass is needed here (avoids N+1).
    return await list_conversations(
        conn,
        user_id=request.state.user_id,
        state=state,
        context_node_id=context_node_id,
        limit=limit,
        offset=offset,
    )


# ---------------------------------------------------------------------------
# POST /conversations
# ---------------------------------------------------------------------------


@router.post("/conversations", status_code=201)
async def create_conv(
    body: ConversationCreate,
    request: Request,
    _auth=Depends(auth_dependency),
    conn=Depends(get_db_conn),
):
    user_id = request.state.user_id
    cid = await create_conversation(
        conn,
        user_id=user_id,
        name=body.name,
        notification_type="bot",
        priority=body.priority,
        context_node_id=body.context_node_id,
        thread_key=body.thread_key,
    )
    conv = await get_conversation(conn, cid)
    return await _attach_folder_name(conn, conv)


# ---------------------------------------------------------------------------
# GET /conversations/{conversation_id}
# ---------------------------------------------------------------------------


@router.get("/conversations/{conversation_id}")
async def get_conv(
    conversation_id: str,
    request: Request,
    _auth=Depends(auth_dependency),
    conn=Depends(get_db_conn),
):
    conv = await get_conversation(conn, conversation_id)
    if conv is None or conv["user_id"] != request.state.user_id:
        raise HTTPException(status_code=404, detail="Conversation not found")
    return await _attach_folder_name(conn, conv)


# ---------------------------------------------------------------------------
# PATCH /conversations/{conversation_id}
# ---------------------------------------------------------------------------


@router.patch("/conversations/{conversation_id}")
async def patch_conv(
    conversation_id: str,
    body: ConversationPatch,
    request: Request,
    _auth=Depends(auth_dependency),
    conn=Depends(get_db_conn),
):
    conv = await get_conversation(conn, conversation_id)
    if conv is None or conv["user_id"] != request.state.user_id:
        raise HTTPException(status_code=404, detail="Conversation not found")
    await update_conversation(
        conn,
        conversation_id,
        name=body.name,
        priority=body.priority,
        context_node_id=body.context_node_id,
        state=body.state,
    )
    updated = await get_conversation(conn, conversation_id)
    return await _attach_folder_name(conn, updated)


# ---------------------------------------------------------------------------
# GET /conversations/{conversation_id}/messages
# ---------------------------------------------------------------------------


@router.get("/conversations/{conversation_id}/messages")
async def get_messages(
    conversation_id: str,
    request: Request,
    limit: int = Query(50, ge=1, le=200),
    before_id: str | None = Query(None),
    _auth=Depends(auth_dependency),
    conn=Depends(get_db_conn),
):
    conv = await get_conversation(conn, conversation_id)
    if conv is None or conv["user_id"] != request.state.user_id:
        raise HTTPException(status_code=404, detail="Conversation not found")
    return await list_conversation_messages(
        conn,
        conversation_id,
        limit=limit,
        before_id=before_id,
    )


# ---------------------------------------------------------------------------
# PUT /preferences/notifications
# ---------------------------------------------------------------------------

@router.put("/preferences/notifications")
async def put_notification_prefs(
    body: NotificationPrefsBody,
    request: Request,
    _auth=Depends(auth_dependency),
    conn=Depends(get_db_conn),
):
    user_id = request.state.user_id

    if body.mode is not None:
        if body.mode not in _NOTIF_MODES:
            raise HTTPException(
                status_code=422,
                detail=f"mode must be one of: {sorted(_NOTIF_MODES)}",
            )
        await upsert_user_preference(conn, user_id, "notif_mode", body.mode)

    if body.priority_threshold is not None:
        await upsert_user_preference(
            conn, user_id, "notif_priority_threshold", body.priority_threshold
        )

    if body.channels is not None:
        invalid = set(body.channels) - _CHANNELS
        if invalid:
            raise HTTPException(
                status_code=422,
                detail=f"unknown channels: {sorted(invalid)}; valid: {sorted(_CHANNELS)}",
            )
        await upsert_user_preference(
            conn, user_id, "notif_channels", json.dumps(body.channels)
        )

    return {"ok": True}


@router.get("/preferences/notifications")
async def get_notification_prefs(
    request: Request,
    _auth=Depends(auth_dependency),
    conn=Depends(get_db_conn),
):
    user_id = request.state.user_id
    prefs = await get_user_preferences(conn, user_id)
    channels_raw = prefs.get("notif_channels")
    channels = json.loads(channels_raw) if channels_raw else []
    return {
        "mode": prefs.get("notif_mode"),
        "priority_threshold": prefs.get("notif_priority_threshold"),
        "channels": channels,
    }


# ---------------------------------------------------------------------------
# GET /context-nodes/{node_id}/summary
# ---------------------------------------------------------------------------


@router.get("/context-nodes/{node_id}/summary")
async def get_node_summary(
    node_id: str,
    _auth=Depends(auth_dependency),
    conn=Depends(get_db_conn),
):
    node = await get_node(conn, node_id)
    if node is None:
        raise HTTPException(status_code=404, detail="Context node not found")
    return {"id": node_id, "summary": node.get("summary")}
