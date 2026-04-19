"""Tests for task context routes using the single context_subject model."""
import pytest
from db.pg_queries import create_unscheduled_task, upsert_context_entry, get_task_by_uuid


@pytest.mark.asyncio
async def test_get_task_contexts_returns_list_with_subject(api_client, conn):
    await upsert_context_entry(conn, "Tether", "Tether ADHD planner project.")
    task = await create_unscheduled_task(conn, "Deploy backend", context_subject="Tether")
    resp = await api_client.get(f"/api/tasks/{task['id']}/contexts")
    assert resp.status_code == 200
    assert resp.json() == ["Tether"]


@pytest.mark.asyncio
async def test_get_task_contexts_returns_empty_list_when_no_context(api_client, conn):
    task = await create_unscheduled_task(conn, "Some backlog task")
    resp = await api_client.get(f"/api/tasks/{task['id']}/contexts")
    assert resp.status_code == 200
    assert resp.json() == []


@pytest.mark.asyncio
async def test_get_task_contexts_404_for_unknown_task(api_client, conn):
    resp = await api_client.get("/api/tasks/00000000-0000-0000-0000-000000000000/contexts")
    assert resp.status_code == 404


@pytest.mark.asyncio
async def test_post_context_sets_context_subject(api_client, conn):
    await upsert_context_entry(conn, "Tether", "Tether ADHD planner project.")
    task = await create_unscheduled_task(conn, "Write tests")
    resp = await api_client.post(
        f"/api/tasks/{task['id']}/contexts",
        json={"subject": "Tether"},
    )
    assert resp.status_code == 200
    assert resp.json() == {"ok": True}

    updated = await get_task_by_uuid(conn, task["id"])
    assert updated["context_subject"] == "Tether"


@pytest.mark.asyncio
async def test_post_context_replaces_existing_context(api_client, conn):
    await upsert_context_entry(conn, "Tether", "Tether ADHD planner project.")
    await upsert_context_entry(conn, "Job Applications", "ML engineer roles.")
    task = await create_unscheduled_task(conn, "Write tests", context_subject="Tether")
    resp = await api_client.post(
        f"/api/tasks/{task['id']}/contexts",
        json={"subject": "Job Applications"},
    )
    assert resp.status_code == 200

    updated = await get_task_by_uuid(conn, task["id"])
    assert updated["context_subject"] == "Job Applications"


@pytest.mark.asyncio
async def test_delete_context_clears_context_subject(api_client, conn):
    await upsert_context_entry(conn, "Tether", "Tether ADHD planner project.")
    task = await create_unscheduled_task(conn, "Write tests", context_subject="Tether")
    resp = await api_client.delete(f"/api/tasks/{task['id']}/contexts/Tether")
    assert resp.status_code == 200
    assert resp.json() == {"ok": True}

    updated = await get_task_by_uuid(conn, task["id"])
    assert updated["context_subject"] is None


@pytest.mark.asyncio
async def test_get_contexts_after_set_then_clear(api_client, conn):
    """Round-trip: set via POST, confirm GET returns list, clear via DELETE, confirm empty."""
    await upsert_context_entry(conn, "Tether", "Tether ADHD planner project.")
    task = await create_unscheduled_task(conn, "Round trip task")
    # Set
    await api_client.post(f"/api/tasks/{task['id']}/contexts", json={"subject": "Tether"})
    # Confirm
    resp = await api_client.get(f"/api/tasks/{task['id']}/contexts")
    assert resp.json() == ["Tether"]
    # Clear
    await api_client.delete(f"/api/tasks/{task['id']}/contexts/Tether")
    # Confirm empty
    resp = await api_client.get(f"/api/tasks/{task['id']}/contexts")
    assert resp.json() == []
