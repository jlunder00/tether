"""Meeting request endpoints."""
from __future__ import annotations

import logging
from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
import asyncpg
from typing import Optional

log = logging.getLogger(__name__)

from api.auth import auth_dependency
from db.pool_middleware import get_db_conn
from db.pg_auth_queries import get_user_by_username, get_user_by_id
from db.pg_queries.scheduling import (
    create_meeting_request,
    create_proposal,
    accept_meeting_slot,
    cancel_meeting,
    get_meeting_request,
    list_meetings_for_user,
    list_incoming_for_user,
    get_connection_by_users,
    get_participants,
)
from api.ws import manager

router = APIRouter()


async def _broadcast_to_bot(event: dict) -> None:
    """Broadcast a meeting event to the bot's __bot__ channel.

    Logs a warning when no bot is connected so dropped events are detectable
    in the API logs during bot restarts or auth failures.
    """
    if not manager._connections.get("__bot__"):
        log.warning("__bot__ broadcast: no bot listeners connected — event dropped: %s", event.get("type"))
    await manager.broadcast({"__bot__": True, **event}, "__bot__")


class MeetingRequestBody(BaseModel):
    target_usernames: list[str]
    duration_minutes: int = 30
    slots: list[str]
    context: Optional[str] = None


class ProposeBody(BaseModel):
    slots: list[str]
    message: Optional[str] = None


class AcceptSlotBody(BaseModel):
    slot: str


@router.post("/meetings/request", status_code=201)
async def request_meeting(
    body: MeetingRequestBody,
    auth=Depends(auth_dependency),
    conn: asyncpg.Connection = Depends(get_db_conn),
):
    caller_id = auth["user_id"]
    caller_username = auth["username"]

    if not body.slots:
        raise HTTPException(status_code=400, detail="slots cannot be empty")

    # Resolve target usernames to user IDs
    target_ids = []
    for username in body.target_usernames:
        user = await get_user_by_username(conn, username)
        if not user:
            raise HTTPException(status_code=404, detail=f"User '{username}' not found")
        target_ids.append(user["id"])

    # Verify each target has an accepted connection with caller
    for target_id in target_ids:
        connection = await get_connection_by_users(conn, caller_id, target_id)
        if not connection or connection["status"] != "accepted":
            raise HTTPException(
                status_code=400,
                detail=f"No accepted connection with one or more targets",
            )

    request = await create_meeting_request(
        conn, caller_id, target_ids, body.duration_minutes, body.context, body.slots
    )

    # Broadcast meeting_request event to each target
    meeting_request_event = {
        "type": "meeting_request",
        "request_id": request["id"],
        "from_user": caller_username,
        "duration": body.duration_minutes,
        "context": body.context or "",
    }
    for target_id in target_ids:
        await manager.broadcast(meeting_request_event, target_id)
    await _broadcast_to_bot(meeting_request_event)

    return {"id": request["id"], "status": request["status"], "round": request["round"]}


@router.post("/meetings/incoming")
async def noop_incoming_post():
    """Prevent POST to /meetings/incoming from matching /{id}."""
    raise HTTPException(status_code=405, detail="Method not allowed")


@router.get("/meetings/incoming")
async def list_incoming(
    auth=Depends(auth_dependency),
    conn: asyncpg.Connection = Depends(get_db_conn),
):
    caller_id = auth["user_id"]
    return await list_incoming_for_user(conn, caller_id)


@router.post("/meetings/{meeting_id}/propose", status_code=201)
async def propose_slots(
    meeting_id: int,
    body: ProposeBody,
    auth=Depends(auth_dependency),
    conn: asyncpg.Connection = Depends(get_db_conn),
):
    caller_id = auth["user_id"]
    caller_username = auth["username"]

    request = await get_meeting_request(conn, meeting_id)
    if not request:
        raise HTTPException(status_code=404, detail="Meeting request not found")
    if request["status"] != "open":
        raise HTTPException(status_code=404, detail="Meeting request is not open")
    if caller_id not in request["target_ids"]:
        raise HTTPException(status_code=403, detail="Only targets can propose slots")

    proposal = await create_proposal(conn, meeting_id, caller_id, body.slots, body.message)

    # Broadcast to initiator
    req_after = await get_meeting_request(conn, meeting_id)
    meeting_proposal_event = {
        "type": "meeting_proposal",
        "request_id": meeting_id,
        "round": req_after["round"],
        "proposed_by": caller_username,
    }
    await manager.broadcast(meeting_proposal_event, request["initiator_id"])
    await _broadcast_to_bot(meeting_proposal_event)

    return {
        "proposal_id": proposal["id"],
        "request_id": meeting_id,
        "status": proposal["status"],
    }


@router.post("/meetings/{meeting_id}/accept")
async def accept_slot(
    meeting_id: int,
    body: AcceptSlotBody,
    auth=Depends(auth_dependency),
    conn: asyncpg.Connection = Depends(get_db_conn),
):
    caller_id = auth["user_id"]

    request = await get_meeting_request(conn, meeting_id)
    if not request:
        raise HTTPException(status_code=404, detail="Meeting request not found")
    if caller_id != request["initiator_id"]:
        raise HTTPException(status_code=403, detail="Only initiator can accept a slot")

    try:
        updated = await accept_meeting_slot(conn, meeting_id, body.slot)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))

    # Gather participant usernames for the WS event
    participant_ids = get_participants(updated)
    usernames = []
    for uid in participant_ids:
        user = await get_user_by_id(conn, uid)
        if user:
            usernames.append(user["username"])

    event = {
        "type": "meeting_agreed",
        "request_id": meeting_id,
        "agreed_slot": body.slot,
        "duration_minutes": updated["duration_minutes"],
        "participants": usernames,
    }
    for uid in participant_ids:
        await manager.broadcast(event, uid)
    await _broadcast_to_bot(event)

    return {
        "id": updated["id"],
        "status": updated["status"],
        "agreed_slot": updated["agreed_slot"],
    }


@router.post("/meetings/{meeting_id}/cancel")
async def cancel_meeting_route(
    meeting_id: int,
    auth=Depends(auth_dependency),
    conn: asyncpg.Connection = Depends(get_db_conn),
):
    caller_id = auth["user_id"]

    request = await get_meeting_request(conn, meeting_id)
    if not request:
        raise HTTPException(status_code=404, detail="Meeting request not found")

    participants = get_participants(request)
    if caller_id not in participants:
        raise HTTPException(status_code=403, detail="Not a participant")

    updated = await cancel_meeting(conn, meeting_id)

    event = {"type": "meeting_cancelled", "request_id": meeting_id}
    for uid in participants:
        await manager.broadcast(event, uid)
    await _broadcast_to_bot(event)

    return {"id": updated["id"], "status": updated["status"]}


@router.get("/meetings")
async def list_meetings(
    status: Optional[str] = None,
    auth=Depends(auth_dependency),
    conn: asyncpg.Connection = Depends(get_db_conn),
):
    caller_id = auth["user_id"]
    return await list_meetings_for_user(conn, caller_id, status_filter=status)


@router.get("/meetings/{meeting_id}")
async def get_meeting(
    meeting_id: int,
    auth=Depends(auth_dependency),
    conn: asyncpg.Connection = Depends(get_db_conn),
):
    caller_id = auth["user_id"]
    request = await get_meeting_request(conn, meeting_id)
    if not request:
        raise HTTPException(status_code=404, detail="Meeting request not found")

    participants = get_participants(request)
    if caller_id not in participants:
        raise HTTPException(status_code=403, detail="Not a participant")

    return request
