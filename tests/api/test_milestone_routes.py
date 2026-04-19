import pytest
from datetime import date
from db.pg_queries import upsert_anchor, upsert_plan, upsert_tasks, upsert_context_entry

ANCHOR = {
    "id": "grind_am", "name": "The Grind", "time": "08:00",
    "duration_minutes": 120, "flexibility": "locked",
    "strictness": 4, "color": "#e05c5c", "position": 1,
}


@pytest.mark.asyncio
async def test_create_milestone(api_client, conn):
    await upsert_context_entry(conn, "Proj", "body")
    resp = await api_client.post("/api/context/Proj/milestones", json={"name": "Goal A"})
    assert resp.status_code == 200
    data = resp.json()
    assert len(data["id"]) == 36
    assert data["name"] == "Goal A"
    assert data["status"] == "pending"


@pytest.mark.asyncio
async def test_list_milestones_for_subject(api_client, conn):
    await upsert_context_entry(conn, "Proj", "body")
    await api_client.post("/api/context/Proj/milestones", json={"name": "M1"})
    await api_client.post("/api/context/Proj/milestones", json={"name": "M2"})
    resp = await api_client.get("/api/context/Proj/milestones")
    assert resp.status_code == 200
    assert len(resp.json()) == 2


@pytest.mark.asyncio
async def test_get_all_milestones(api_client, conn):
    await upsert_context_entry(conn, "Proj", "body")
    await upsert_context_entry(conn, "Other", "body2")
    await api_client.post("/api/context/Proj/milestones", json={"name": "M1"})
    await api_client.post("/api/context/Other/milestones", json={"name": "M2"})
    resp = await api_client.get("/api/milestones")
    assert resp.status_code == 200
    assert len(resp.json()) == 2


@pytest.mark.asyncio
async def test_patch_milestone(api_client, conn):
    await upsert_context_entry(conn, "Proj", "body")
    mid = (await api_client.post("/api/context/Proj/milestones", json={"name": "Old"})).json()["id"]
    resp = await api_client.patch(f"/api/milestones/{mid}", json={"name": "New"})
    assert resp.status_code == 200
    assert resp.json()["name"] == "New"


@pytest.mark.asyncio
async def test_patch_milestone_status_sets_override(api_client, conn):
    await upsert_context_entry(conn, "Proj", "body")
    mid = (await api_client.post("/api/context/Proj/milestones", json={"name": "Goal"})).json()["id"]
    resp = await api_client.patch(f"/api/milestones/{mid}", json={"status": "done"})
    assert resp.status_code == 200
    assert resp.json()["status"] == "done"
    assert resp.json()["status_override"] is True


@pytest.mark.asyncio
async def test_patch_milestone_not_found(api_client, conn):
    resp = await api_client.patch("/api/milestones/00000000-0000-0000-0000-000000000000", json={"name": "x"})
    assert resp.status_code == 404


@pytest.mark.asyncio
async def test_delete_milestone(api_client, conn):
    await upsert_context_entry(conn, "Proj", "body")
    mid = (await api_client.post("/api/context/Proj/milestones", json={"name": "Del"})).json()["id"]
    del_resp = await api_client.delete(f"/api/milestones/{mid}")
    list_resp = await api_client.get("/api/context/Proj/milestones")
    assert del_resp.status_code == 200
    assert list_resp.json() == []


@pytest.mark.asyncio
async def test_link_and_unlink_task(api_client, conn):
    await upsert_context_entry(conn, "Proj", "body")
    await upsert_anchor(conn, ANCHOR)
    await upsert_plan(conn, str(date.today()))
    tasks = await upsert_tasks(conn, str(date.today()), "grind_am", [{"text": "T1"}], notes="")
    task_id = tasks[0]["id"]
    mid = (await api_client.post("/api/context/Proj/milestones", json={"name": "Goal"})).json()["id"]
    await api_client.post(f"/api/milestones/{mid}/tasks", json={"task_id": task_id})
    linked = (await api_client.get("/api/context/Proj/milestones")).json()
    await api_client.delete(f"/api/milestones/{mid}/tasks/{task_id}")
    unlinked = (await api_client.get("/api/context/Proj/milestones")).json()
    assert task_id in linked[0]["task_ids"]
    assert unlinked[0]["task_ids"] == []
