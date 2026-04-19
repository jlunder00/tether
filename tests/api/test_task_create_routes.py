"""Tests for POST /tasks/unscheduled — contextual creation with metadata."""
import pytest
from datetime import date
from db.pg_queries import (
    upsert_anchor, upsert_plan, upsert_context_entry,
    create_milestone, get_task_by_uuid,
)

ANCHOR_ID = "00000000-0000-0000-0000-000000000010"
ANCHOR = {
    "id": ANCHOR_ID, "name": "The Grind", "time": "08:00",
    "duration_minutes": 120, "flexibility": "locked",
    "strictness": 4, "color": "#e05c5c", "position": 1,
}


@pytest.mark.asyncio
async def test_create_task_minimal(api_client, conn):
    resp = await api_client.post("/api/tasks/unscheduled", json={"text": "Hello"})
    assert resp.status_code == 200
    data = resp.json()
    assert data["text"] == "Hello"
    assert data["plan_date"] is None
    assert data["anchor_id"] is None


@pytest.mark.asyncio
async def test_create_task_with_context_and_schedule(api_client, conn):
    today = str(date.today())
    await upsert_anchor(conn, ANCHOR)
    await upsert_plan(conn, today)
    await upsert_context_entry(conn, "Proj", "body")
    resp = await api_client.post("/api/tasks/unscheduled", json={
        "text": "Scheduled task",
        "context_subject": "Proj",
        "date": today,
        "anchor_id": ANCHOR_ID,
    })
    assert resp.status_code == 200
    data = resp.json()
    assert data["context_subject"] == "Proj"
    assert data["plan_date"] == today
    assert data["anchor_id"] == ANCHOR_ID


@pytest.mark.asyncio
async def test_create_task_links_milestone(api_client, conn):
    await upsert_context_entry(conn, "Proj", "body")
    milestone = await create_milestone(conn, "Proj", "M1")
    resp = await api_client.post("/api/tasks/unscheduled", json={
        "text": "With milestone",
        "context_subject": "Proj",
        "milestone_id": milestone["id"],
    })
    assert resp.status_code == 200
    task_id = resp.json()["id"]
    row = await conn.fetchrow(
        "SELECT milestone_id FROM milestone_tasks WHERE task_id = $1",
        task_id,
    )
    assert row is not None
    assert str(row["milestone_id"]) == milestone["id"]


@pytest.mark.asyncio
async def test_create_task_bad_milestone_rolls_back(api_client, conn):
    """Invalid milestone_id should roll back the create (FK violation)."""
    resp = await api_client.post("/api/tasks/unscheduled", json={
        "text": "Should not persist",
        "milestone_id": "00000000-0000-0000-0000-deadbeef0000",
    })
    # The backend surfaces the FK error as a 4xx/5xx; the task should not be in the DB
    assert resp.status_code >= 400
    row = await conn.fetchrow(
        "SELECT COUNT(*) AS n FROM tasks WHERE text = $1",
        "Should not persist",
    )
    assert row["n"] == 0
