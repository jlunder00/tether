import pytest
from datetime import date
from httpx import AsyncClient, ASGITransport
from pathlib import Path
from db.schema import init_db
from db.queries import upsert_anchor, upsert_plan, upsert_tasks
from api.main import create_app


@pytest.fixture
def db_path(tmp_path):
    path = tmp_path / "tether.db"
    init_db(path)
    upsert_anchor(path, {"id": "grind_am", "name": "The Grind", "time": "08:00",
                          "duration_minutes": 120, "flexibility": "locked",
                          "strictness": 4, "color": "#e05c5c", "position": 0})
    today = str(date.today())
    upsert_plan(path, today)
    upsert_tasks(path, today, "grind_am", tasks=["Apply to jobs"], notes="ML roles")
    return path


@pytest.fixture
def app(db_path):
    return create_app(db_path=db_path)


@pytest.mark.asyncio
async def test_get_plan_returns_date(app):
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        resp = await client.get(f"/api/plan/{date.today()}")
    assert resp.status_code == 200
    assert resp.json()["date"] == str(date.today())


@pytest.mark.asyncio
async def test_get_plan_returns_anchors(app):
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        resp = await client.get(f"/api/plan/{date.today()}")
    assert "grind_am" in resp.json()["anchors"]


@pytest.mark.asyncio
async def test_put_anchor_tasks_updates_db(app, db_path):
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        resp = await client.put(
            f"/api/plan/{date.today()}/anchors/grind_am",
            json={"tasks": ["Updated task"], "notes": ""}
        )
    assert resp.status_code == 200
    from db.queries import get_plan
    plan = get_plan(db_path, str(date.today()))
    assert [t["text"] for t in plan["anchors"]["grind_am"]["tasks"]] == ["Updated task"]


@pytest.mark.asyncio
async def test_get_anchors(app):
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        resp = await client.get("/api/anchors")
    assert resp.status_code == 200
    assert any(a["id"] == "grind_am" for a in resp.json())


@pytest.mark.asyncio
async def test_put_anchor_tasks_returns_task_objects(app, db_path):
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        resp = await client.put(
            f"/api/plan/{date.today()}/anchors/grind_am",
            json={"tasks": [{"text": "New task", "status": "pending"}], "notes": ""}
        )
    assert resp.status_code == 200
    data = resp.json()
    assert data["ok"] is True
    assert len(data["tasks"]) == 1
    assert len(data["tasks"][0]["id"]) == 36
    assert data["tasks"][0]["text"] == "New task"


@pytest.mark.asyncio
async def test_get_plan_returns_task_objects_with_status(app):
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        resp = await client.get(f"/api/plan/{date.today()}")
    task = resp.json()["anchors"]["grind_am"]["tasks"][0]
    assert isinstance(task, dict)
    assert "id" in task and "status" in task


@pytest.mark.asyncio
async def test_patch_task_status(app, db_path):
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        put_resp = await client.put(
            f"/api/plan/{date.today()}/anchors/grind_am",
            json={"tasks": [{"text": "Task"}], "notes": ""}
        )
        task_id = put_resp.json()["tasks"][0]["id"]
        resp = await client.patch(f"/api/tasks/{task_id}", json={"status": "in_progress"})
    assert resp.status_code == 200
    assert resp.json()["status"] == "in_progress"


@pytest.mark.asyncio
async def test_patch_task_not_found(app):
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        resp = await client.patch("/api/tasks/nonexistent-uuid", json={"status": "done"})
    assert resp.status_code == 404


@pytest.mark.asyncio
async def test_move_task(app, db_path):
    from datetime import timedelta
    today = str(date.today())
    tomorrow = str(date.today() + timedelta(days=1))
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        put_resp = await client.put(
            f"/api/plan/{today}/anchors/grind_am",
            json={"tasks": [{"text": "Move me"}], "notes": ""}
        )
        task_id = put_resp.json()["tasks"][0]["id"]
        resp = await client.put(
            f"/api/tasks/{task_id}/move",
            json={"date": tomorrow, "anchor_id": "grind_am"}
        )
    assert resp.status_code == 200
    assert resp.json()["ok"] is True


@pytest.mark.asyncio
async def test_get_plan_range_returns_dict_of_day_plans(app, db_path):
    from datetime import date, timedelta
    today = str(date.today())
    tomorrow = str(date.today() + timedelta(days=1))
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        resp = await client.get(f"/api/plan/range?start={today}&end={tomorrow}")
    assert resp.status_code == 200
    data = resp.json()
    assert today in data
    assert tomorrow in data
    assert "anchors" in data[today]
