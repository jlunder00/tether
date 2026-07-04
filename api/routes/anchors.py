import logging
from datetime import datetime

from fastapi import APIRouter, Depends, Request
from pydantic import BaseModel
from typing import Literal
import asyncpg
from db.pg_queries import get_anchors, upsert_anchor, delete_anchor
from db.pool_middleware import get_db_conn
from bot.crontab import sync_crontab
from api.ws import manager
from api.auth import auth_dependency
from shared import notify_due

logger = logging.getLogger(__name__)

router = APIRouter()


async def _refresh_anchor_due_cache(conn: asyncpg.Connection, user_id: str) -> None:
    """Refresh the cached anchor schedule + the "anchor" Redis due-component
    for *user_id* after any anchor create/update/delete.

    Anchor edits are rare and already happen inside an authenticated,
    synchronous request — recomputing here (rather than waiting for the
    next real notification check) keeps the gate accurate immediately
    instead of lagging behind an edit by up to the safety TTL. See
    shared/notify_due.py for the full gating scheme.

    Best-effort: this is a cache-warming side effect of a successful anchor
    mutation, not part of the mutation itself. ANY failure here (a Postgres
    blip re-reading anchors, a malformed row, Redis being unreachable) must
    never turn an already-committed create/update/delete into a user-facing
    error, and must never suppress the ``anchors_updated`` WS broadcast the
    caller sends right after this. Errors are logged and swallowed — the
    gate simply stays stale until the next real notification check
    self-heals it (or the safety TTL expires it), which is a performance
    detail, not a correctness one.
    """
    try:
        anchors = await get_anchors(conn)
        await notify_due.set_cached_anchors(user_id, anchors)
        next_boundary = notify_due.next_anchor_boundary(anchors, datetime.now())
        if next_boundary is not None:
            await notify_due.set_component_due(user_id, "anchor", next_boundary.timestamp())
    except Exception:
        logger.warning(
            "anchor due-cache refresh failed for user_id=%s — mutation already "
            "committed; gate will self-heal on the next real notification check",
            user_id, exc_info=True,
        )


class AnchorUpdate(BaseModel):
    name: str
    time: str
    duration_minutes: int
    flexibility: str
    strictness: int
    color: str
    position: int
    followup_config: dict | None = None
    motif: Literal["anchor", "focus", "calm", "energy", "care", "flow", "dusk", "quiet"] = "anchor"


@router.get("/anchors")
async def get_anchors_route(_auth=Depends(auth_dependency),
                            conn: asyncpg.Connection = Depends(get_db_conn)):
    return await get_anchors(conn)


@router.post("/anchors")
async def create_anchor(body: AnchorUpdate, request: Request,
                        _auth=Depends(auth_dependency),
                        conn: asyncpg.Connection = Depends(get_db_conn)):
    import uuid
    anchor_id = str(uuid.uuid4())
    anchor = {"id": anchor_id, **body.model_dump()}
    await upsert_anchor(conn, anchor)
    await sync_crontab(request.app.state.pool, request.state.user_id)
    await _refresh_anchor_due_cache(conn, request.state.user_id)
    await manager.broadcast({"type": "anchors_updated"}, request.state.user_id)
    return anchor


@router.put("/anchors/{anchor_id}")
async def update_anchor(anchor_id: str, body: AnchorUpdate, request: Request,
                        _auth=Depends(auth_dependency),
                        conn: asyncpg.Connection = Depends(get_db_conn)):
    anchor = {"id": anchor_id, **body.model_dump()}
    await upsert_anchor(conn, anchor)
    await sync_crontab(request.app.state.pool, request.state.user_id)
    await _refresh_anchor_due_cache(conn, request.state.user_id)
    await manager.broadcast({"type": "anchors_updated"}, request.state.user_id)
    return anchor


@router.delete("/anchors/{anchor_id}")
async def delete_anchor_route(anchor_id: str, request: Request,
                              _auth=Depends(auth_dependency),
                              conn: asyncpg.Connection = Depends(get_db_conn)):
    await delete_anchor(conn, anchor_id)
    await sync_crontab(request.app.state.pool, request.state.user_id)
    await _refresh_anchor_due_cache(conn, request.state.user_id)
    await manager.broadcast({"type": "anchors_updated"}, request.state.user_id)
    return {"ok": True}
