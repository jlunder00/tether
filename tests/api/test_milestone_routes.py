import pytest
from datetime import date
from db.schema import init_db
from db.queries import upsert_anchor, upsert_plan, upsert_tasks, upsert_context_entry
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
async def test_create_milestone(app, db_path):
    async with make_authenticated_client(app, db_path) as client:
        resp = await client.post("/api/context/Proj/milestones", json={"name": "Goal A"})
    assert resp.status_code == 200
    data = resp.json()
    assert len(data["id"]) == 36
    assert data["name"] == "Goal A"
    assert data["status"] == "pending"


@pytest.mark.asyncio
async def test_list_milestones_for_subject(app, db_path):
    async with make_authenticated_client(app, db_path) as client:
        await client.post("/api/context/Proj/milestones", json={"name": "M1"})
        await client.post("/api/context/Proj/milestones", json={"name": "M2"})
        resp = await client.get("/api/context/Proj/milestones")
    assert resp.status_code == 200
    assert len(resp.json()) == 2


@pytest.mark.asyncio
async def test_get_all_milestones(app, db_path):
    upsert_context_entry(db_path, "Other", "body2")
    async with make_authenticated_client(app, db_path) as client:
        await client.post("/api/context/Proj/milestones", json={"name": "M1"})
        await client.post("/api/context/Other/milestones", json={"name": "M2"})
        resp = await client.get("/api/milestones")
    assert resp.status_code == 200
    assert len(resp.json()) == 2


@pytest.mark.asyncio
async def test_patch_milestone(app, db_path):
    async with make_authenticated_client(app, db_path) as client:
        mid = (await client.post("/api/context/Proj/milestones", json={"name": "Old"})).json()["id"]
        resp = await client.patch(f"/api/milestones/{mid}", json={"name": "New"})
    assert resp.status_code == 200
    assert resp.json()["name"] == "New"


@pytest.mark.asyncio
async def test_patch_milestone_status_sets_override(app, db_path):
    async with make_authenticated_client(app, db_path) as client:
        mid = (await client.post("/api/context/Proj/milestones", json={"name": "Goal"})).json()["id"]
        resp = await client.patch(f"/api/milestones/{mid}", json={"status": "done"})
    assert resp.status_code == 200
    assert resp.json()["status"] == "done"
    assert resp.json()["status_override"] is True


@pytest.mark.asyncio
async def test_patch_milestone_not_found(app, db_path):
    async with make_authenticated_client(app, db_path) as client:
        resp = await client.patch("/api/milestones/nonexistent", json={"name": "x"})
    assert resp.status_code == 404


@pytest.mark.asyncio
async def test_delete_milestone(app, db_path):
    async with make_authenticated_client(app, db_path) as client:
        mid = (await client.post("/api/context/Proj/milestones", json={"name": "Del"})).json()["id"]
        del_resp = await client.delete(f"/api/milestones/{mid}")
        list_resp = await client.get("/api/context/Proj/milestones")
    assert del_resp.status_code == 200
    assert list_resp.json() == []


@pytest.mark.asyncio
async def test_link_and_unlink_task(app, db_path):
    tasks = upsert_tasks(db_path, str(date.today()), "grind_am", [{"text": "T1"}], notes="")
    task_id = tasks[0]["id"]
    async with make_authenticated_client(app, db_path) as client:
        mid = (await client.post("/api/context/Proj/milestones", json={"name": "Goal"})).json()["id"]
        await client.post(f"/api/milestones/{mid}/tasks", json={"task_id": task_id})
        linked = (await client.get("/api/context/Proj/milestones")).json()
        await client.delete(f"/api/milestones/{mid}/tasks/{task_id}")
        unlinked = (await client.get("/api/context/Proj/milestones")).json()
    assert task_id in linked[0]["task_ids"]
    assert unlinked[0]["task_ids"] == []
