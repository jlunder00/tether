"""Tests for POST /tasks/unscheduled — contextual creation with metadata."""
import pytest
from datetime import date
from db.schema import init_db, get_db
from db.queries import (
    upsert_anchor, upsert_plan, upsert_context_entry,
    create_milestone, get_task_by_uuid,
)
from api.main import create_app
from tests.api.conftest import make_authenticated_client

ANCHOR = {
    "id": "grind_am", "name": "The Grind", "time": "08:00",
    "duration_minutes": 120, "flexibility": "locked",
    "strictness": 4, "color": "#e05c5c", "position": 1,
}


@pytest.fixture
def db_path(tmp_path):
    path = tmp_path / "tether.db"
    init_db(path)
    upsert_anchor(path, ANCHOR)
    upsert_plan(path, str(date.today()))
    upsert_context_entry(path, "Proj", "body")
    return path


@pytest.fixture
def app(db_path):
    return create_app(db_path=db_path)


@pytest.mark.asyncio
async def test_create_task_minimal(app, db_path):
    async with make_authenticated_client(app, db_path) as client:
        resp = await client.post("/api/tasks/unscheduled", json={"text": "Hello"})
    assert resp.status_code == 200
    data = resp.json()
    assert data["text"] == "Hello"
    assert data["plan_date"] is None
    assert data["anchor_id"] is None


@pytest.mark.asyncio
async def test_create_task_with_context_and_schedule(app, db_path):
    today = str(date.today())
    async with make_authenticated_client(app, db_path) as client:
        resp = await client.post("/api/tasks/unscheduled", json={
            "text": "Scheduled task",
            "context_subject": "Proj",
            "date": today,
            "anchor_id": "grind_am",
        })
    assert resp.status_code == 200
    data = resp.json()
    assert data["context_subject"] == "Proj"
    assert data["plan_date"] == today
    assert data["anchor_id"] == "grind_am"


@pytest.mark.asyncio
async def test_create_task_links_milestone(app, db_path):
    milestone = create_milestone(db_path, "Proj", "M1")
    async with make_authenticated_client(app, db_path) as client:
        resp = await client.post("/api/tasks/unscheduled", json={
            "text": "With milestone",
            "context_subject": "Proj",
            "milestone_id": milestone["id"],
        })
    assert resp.status_code == 200
    task_id = resp.json()["id"]
    with get_db(db_path) as conn:
        row = conn.execute(
            "SELECT milestone_id FROM milestone_tasks WHERE task_id=?",
            (task_id,),
        ).fetchone()
    assert row is not None
    assert row["milestone_id"] == milestone["id"]


@pytest.mark.asyncio
async def test_create_task_bad_milestone_rolls_back(app, db_path):
    """Invalid milestone_id should roll back the create (FK violation)."""
    async with make_authenticated_client(app, db_path) as client:
        resp = await client.post("/api/tasks/unscheduled", json={
            "text": "Should not persist",
            "milestone_id": "00000000-0000-0000-0000-deadbeef0000",
        })
    # The backend surfaces the FK error as a 500; the task should not be in the DB
    assert resp.status_code >= 400
    with get_db(db_path) as conn:
        row = conn.execute("SELECT COUNT(*) AS n FROM tasks WHERE text='Should not persist'").fetchone()
    assert row["n"] == 0
