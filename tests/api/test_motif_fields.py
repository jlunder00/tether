"""Motif field round-trip tests for tasks, context_entries, and milestones."""
import pytest
from db.pg_queries import upsert_context_entry


@pytest.mark.asyncio
async def test_post_task_with_motif(api_client, conn):
    resp = await api_client.post(
        "/api/tasks/unscheduled", json={"text": "Task A", "motif": "focus"}
    )
    assert resp.status_code == 200
    task_id = resp.json()["id"]

    resp = await api_client.get(f"/api/tasks/{task_id}")
    assert resp.status_code == 200
    assert resp.json()["motif"] == "focus"


@pytest.mark.asyncio
async def test_post_task_default_motif(api_client, conn):
    resp = await api_client.post("/api/tasks/unscheduled", json={"text": "Task B"})
    assert resp.status_code == 200
    task_id = resp.json()["id"]
    assert resp.json()["motif"] == "anchor"

    resp = await api_client.get(f"/api/tasks/{task_id}")
    assert resp.json()["motif"] == "anchor"


@pytest.mark.asyncio
async def test_post_task_invalid_motif(api_client, conn):
    resp = await api_client.post(
        "/api/tasks/unscheduled", json={"text": "Task C", "motif": "invalid"}
    )
    assert resp.status_code == 422


@pytest.mark.asyncio
async def test_patch_task_motif(api_client, conn):
    resp = await api_client.post("/api/tasks/unscheduled", json={"text": "Task D"})
    task_id = resp.json()["id"]

    resp = await api_client.patch(f"/api/tasks/{task_id}", json={"motif": "calm"})
    assert resp.status_code == 200
    assert resp.json()["motif"] == "calm"

    resp = await api_client.get(f"/api/tasks/{task_id}")
    assert resp.json()["motif"] == "calm"


@pytest.mark.asyncio
async def test_patch_task_invalid_motif(api_client, conn):
    resp = await api_client.post("/api/tasks/unscheduled", json={"text": "Task E"})
    task_id = resp.json()["id"]
    resp = await api_client.patch(f"/api/tasks/{task_id}", json={"motif": "bogus"})
    assert resp.status_code == 422


@pytest.mark.asyncio
async def test_put_context_with_motif(api_client, conn):
    resp = await api_client.put(
        "/api/context/MotifProj", json={"body": "hello", "motif": "energy"}
    )
    assert resp.status_code == 200

    resp = await api_client.get("/api/context/MotifProj")
    assert resp.status_code == 200
    assert resp.json()["motif"] == "energy"


@pytest.mark.asyncio
async def test_put_context_default_motif(api_client, conn):
    resp = await api_client.put("/api/context/MotifProj2", json={"body": "hi"})
    assert resp.status_code == 200

    resp = await api_client.get("/api/context/MotifProj2")
    assert resp.json()["motif"] == "anchor"


@pytest.mark.asyncio
async def test_put_context_invalid_motif(api_client, conn):
    resp = await api_client.put(
        "/api/context/MotifProj3", json={"body": "x", "motif": "nope"}
    )
    assert resp.status_code == 422


@pytest.mark.asyncio
async def test_post_milestone_with_motif(api_client, conn):
    await upsert_context_entry(conn, "MProj", "body")
    resp = await api_client.post(
        "/api/context/MProj/milestones",
        json={"name": "M1", "motif": "flow"},
    )
    assert resp.status_code == 200
    milestone_id = resp.json()["id"]
    assert resp.json()["motif"] == "flow"

    resp = await api_client.get("/api/context/MProj/milestones")
    matched = next(m for m in resp.json() if m["id"] == milestone_id)
    assert matched["motif"] == "flow"


@pytest.mark.asyncio
async def test_post_milestone_default_motif(api_client, conn):
    await upsert_context_entry(conn, "MProj2", "body")
    resp = await api_client.post(
        "/api/context/MProj2/milestones", json={"name": "M2"}
    )
    assert resp.status_code == 200
    assert resp.json()["motif"] == "anchor"


@pytest.mark.asyncio
async def test_post_milestone_invalid_motif(api_client, conn):
    await upsert_context_entry(conn, "MProj3", "body")
    resp = await api_client.post(
        "/api/context/MProj3/milestones",
        json={"name": "M3", "motif": "weird"},
    )
    assert resp.status_code == 422


@pytest.mark.asyncio
async def test_patch_milestone_motif(api_client, conn):
    await upsert_context_entry(conn, "MProj4", "body")
    resp = await api_client.post(
        "/api/context/MProj4/milestones", json={"name": "M4"}
    )
    milestone_id = resp.json()["id"]

    resp = await api_client.patch(
        f"/api/milestones/{milestone_id}", json={"motif": "dusk"}
    )
    assert resp.status_code == 200
    assert resp.json()["motif"] == "dusk"


@pytest.mark.asyncio
async def test_patch_milestone_invalid_motif(api_client, conn):
    await upsert_context_entry(conn, "MProj5", "body")
    resp = await api_client.post(
        "/api/context/MProj5/milestones", json={"name": "M5"}
    )
    milestone_id = resp.json()["id"]
    resp = await api_client.patch(
        f"/api/milestones/{milestone_id}", json={"motif": "huh"}
    )
    assert resp.status_code == 422
