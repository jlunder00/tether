"""Tests for task context routes using the single context_subject model."""
import pytest
from db.schema import init_db
from db.queries import create_unscheduled_task, upsert_context_entry
from api.main import create_app
from tests.api.conftest import make_authenticated_client


@pytest.fixture
def db_path(tmp_path):
    path = tmp_path / "tether.db"
    init_db(path)
    upsert_context_entry(path, "Tether", "Tether ADHD planner project.")
    upsert_context_entry(path, "Job Applications", "ML engineer roles.")
    return path


@pytest.fixture
def app(db_path):
    return create_app(db_path=db_path)


# ---------------------------------------------------------------------------
# GET /tasks/{uuid}/contexts — backward compat: returns a list
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_get_task_contexts_returns_list_with_subject(app, db_path):
    task = create_unscheduled_task(db_path, "Deploy backend", context_subject="Tether")
    async with make_authenticated_client(app, db_path) as client:
        resp = await client.get(f"/api/tasks/{task['id']}/contexts")
    assert resp.status_code == 200
    assert resp.json() == ["Tether"]


@pytest.mark.asyncio
async def test_get_task_contexts_returns_empty_list_when_no_context(app, db_path):
    task = create_unscheduled_task(db_path, "Some backlog task")
    async with make_authenticated_client(app, db_path) as client:
        resp = await client.get(f"/api/tasks/{task['id']}/contexts")
    assert resp.status_code == 200
    assert resp.json() == []


@pytest.mark.asyncio
async def test_get_task_contexts_404_for_unknown_task(app, db_path):
    async with make_authenticated_client(app, db_path) as client:
        resp = await client.get("/api/tasks/nonexistent-uuid/contexts")
    assert resp.status_code == 404


# ---------------------------------------------------------------------------
# POST /tasks/{uuid}/contexts — sets context_subject (replaces)
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_post_context_sets_context_subject(app, db_path):
    task = create_unscheduled_task(db_path, "Write tests")
    async with make_authenticated_client(app, db_path) as client:
        resp = await client.post(
            f"/api/tasks/{task['id']}/contexts",
            json={"subject": "Tether"},
        )
    assert resp.status_code == 200
    assert resp.json() == {"ok": True}

    # Verify it was set
    from db.queries import get_task_by_uuid
    updated = get_task_by_uuid(db_path, task["id"])
    assert updated["context_subject"] == "Tether"


@pytest.mark.asyncio
async def test_post_context_replaces_existing_context(app, db_path):
    task = create_unscheduled_task(db_path, "Write tests", context_subject="Tether")
    async with make_authenticated_client(app, db_path) as client:
        resp = await client.post(
            f"/api/tasks/{task['id']}/contexts",
            json={"subject": "Job Applications"},
        )
    assert resp.status_code == 200

    from db.queries import get_task_by_uuid
    updated = get_task_by_uuid(db_path, task["id"])
    assert updated["context_subject"] == "Job Applications"


# ---------------------------------------------------------------------------
# DELETE /tasks/{uuid}/contexts/{subject} — clears context_subject
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_delete_context_clears_context_subject(app, db_path):
    task = create_unscheduled_task(db_path, "Write tests", context_subject="Tether")
    async with make_authenticated_client(app, db_path) as client:
        resp = await client.delete(f"/api/tasks/{task['id']}/contexts/Tether")
    assert resp.status_code == 200
    assert resp.json() == {"ok": True}

    from db.queries import get_task_by_uuid
    updated = get_task_by_uuid(db_path, task["id"])
    assert updated["context_subject"] is None


@pytest.mark.asyncio
async def test_get_contexts_after_set_then_clear(app, db_path):
    """Round-trip: set via POST, confirm GET returns list, clear via DELETE, confirm empty."""
    task = create_unscheduled_task(db_path, "Round trip task")
    async with make_authenticated_client(app, db_path) as client:
        # Set
        await client.post(f"/api/tasks/{task['id']}/contexts", json={"subject": "Tether"})
        # Confirm
        resp = await client.get(f"/api/tasks/{task['id']}/contexts")
        assert resp.json() == ["Tether"]
        # Clear
        await client.delete(f"/api/tasks/{task['id']}/contexts/Tether")
        # Confirm empty
        resp = await client.get(f"/api/tasks/{task['id']}/contexts")
        assert resp.json() == []
