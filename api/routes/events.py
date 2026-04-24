import logging

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
import asyncpg

from db.pg_queries.tasks import promote_task_to_event, get_events_for_range
from db.pool_middleware import get_db_conn
from api.auth import auth_dependency

router = APIRouter()
logger = logging.getLogger(__name__)


class PromoteEventBody(BaseModel):
    task_id: str
    start_time: str
    end_time: str
    title: str | None = None  # informational — task text is already set in the DB


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


@router.get("/events")
async def get_events(
    start: str,
    end: str,
    _auth=Depends(auth_dependency),
    conn: asyncpg.Connection = Depends(get_db_conn),
):
    """Return all calendar events (promoted tasks) whose start_time falls in [start, end]."""
    return await get_events_for_range(conn, start, end)
