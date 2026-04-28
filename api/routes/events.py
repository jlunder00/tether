import logging

from typing import Literal
from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel
import asyncpg

from db.pg_queries.tasks import (
    promote_task_to_event, get_events_for_range, update_event_time,
    patch_recurring_this, patch_recurring_this_and_future,
    delete_event, delete_recurring_occurrence, delete_recurring_from,
)
from db.pool_middleware import get_db_conn
from api.auth import auth_dependency

router = APIRouter()
logger = logging.getLogger(__name__)


class PromoteEventBody(BaseModel):
    task_id: str
    start_time: str
    end_time: str
    title: str | None = None  # informational — task text is already set in the DB


class MoveEventBody(BaseModel):
    start_time: str
    end_time: str
    scope: Literal["all", "this", "this_and_future"] = "all"
    original_start_time: str | None = None


@router.post("/events", status_code=201)
async def post_event(
    body: PromoteEventBody,
    _auth=Depends(auth_dependency),
    conn: asyncpg.Connection = Depends(get_db_conn),
):
    """Promote an existing task to a calendar event by stamping start/end time."""
    event = await promote_task_to_event(
        conn, body.task_id, body.start_time, body.end_time
    )
    if event is None:
        raise HTTPException(status_code=404, detail="Task not found")
    logger.info("events: promoted task %s to event at %s", body.task_id, body.start_time)
    return event


@router.patch("/events/{event_id}")
async def patch_event(
    event_id: str,
    body: MoveEventBody,
    _auth=Depends(auth_dependency),
    conn: asyncpg.Connection = Depends(get_db_conn),
):
    """Reposition a calendar event to a new time slot (move/resize)."""
    if body.scope != "all" and body.original_start_time is None:
        raise HTTPException(
            status_code=422,
            detail='original_start_time is required when scope is not all',
        )

    try:
        if body.scope == "this":
            event = await patch_recurring_this(
                conn, event_id, body.original_start_time, body.start_time, body.end_time,
            )
        elif body.scope == "this_and_future":
            event = await patch_recurring_this_and_future(
                conn, event_id, body.original_start_time, body.start_time, body.end_time,
            )
        else:
            event = await update_event_time(conn, event_id, body.start_time, body.end_time)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc

    if event is None:
        raise HTTPException(status_code=404, detail="Event not found")
    logger.info("events: patched event %s scope=%s to %s", event_id, body.scope, body.start_time)
    return event


@router.get("/events")
async def get_events(
    start: str,
    end: str,
    _auth=Depends(auth_dependency),
    conn: asyncpg.Connection = Depends(get_db_conn),
):
    """Return all calendar events (promoted tasks) whose start_time falls in [start, end]."""
    return await get_events_for_range(conn, start, end)


@router.delete("/events/{event_id}", status_code=204)
async def delete_event_route(
    event_id: str,
    scope: Literal["all", "this", "this_and_future"] = Query(default="all"),
    original_start_time: str | None = Query(default=None),
    _auth=Depends(auth_dependency),
    conn: asyncpg.Connection = Depends(get_db_conn),
):
    """Delete a calendar event or recurring occurrence.

    scope=all (default): hard-delete the event/master + all orphan exceptions.
    scope=this: append an EXDATE to suppress this occurrence only; master persists.
    scope=this_and_future: set UNTIL on the master to truncate future occurrences.

    original_start_time (ISO 8601) is required for scope=this and scope=this_and_future.
    """
    if scope != "all" and original_start_time is None:
        raise HTTPException(
            status_code=422,
            detail="original_start_time is required when scope is not 'all'",
        )

    try:
        if scope == "this":
            found = await delete_recurring_occurrence(conn, event_id, original_start_time)
        elif scope == "this_and_future":
            found = await delete_recurring_from(conn, event_id, original_start_time)
        else:
            found = await delete_event(conn, event_id)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc

    if not found:
        raise HTTPException(status_code=404, detail="Event not found")

    logger.info("events: deleted event %s scope=%s", event_id, scope)
