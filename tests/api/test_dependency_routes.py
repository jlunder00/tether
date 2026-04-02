import pytest
from datetime import date
from db.schema import init_db
from db.queries import upsert_anchor, upsert_plan, upsert_tasks
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
    return path


@pytest.fixture
def app(db_path):
    return create_app(db_path=db_path)


@pytest.fixture
def two_tasks(db_path):
    tasks = upsert_tasks(db_path, str(date.today()), "grind_am",
                         [{"text": "Task 1"}, {"text": "Task 2"}], notes="")
    return tasks[0]["id"], tasks[1]["id"]


@pytest.mark.asyncio
async def test_create_and_get_dependency(app, db_path, two_tasks):
    task_a, task_b = two_tasks
    async with make_authenticated_client(app, db_path) as client:
        resp = await client.post("/api/dependencies", json={
            "blocker_type": "task", "blocker_id": task_a,
            "blocked_type": "task", "blocked_id": task_b,
        })
        assert resp.status_code == 200
        dep_id = resp.json()["id"]
        assert isinstance(dep_id, int)

        # task_a blocks task_b — get deps for task_a
        get_resp = await client.get(f"/api/task/{task_a}/dependencies")
        assert get_resp.status_code == 200
        data = get_resp.json()
        assert len(data["blocks"]) == 1
        assert data["blocks"][0]["entity_id"] == task_b
        assert data["blocked_by"] == []

        # get deps for task_b
        get_resp2 = await client.get(f"/api/task/{task_b}/dependencies")
        assert get_resp2.status_code == 200
        data2 = get_resp2.json()
        assert data2["blocks"] == []
        assert len(data2["blocked_by"]) == 1
        assert data2["blocked_by"][0]["entity_id"] == task_a


@pytest.mark.asyncio
async def test_delete_dependency(app, db_path, two_tasks):
    task_a, task_b = two_tasks
    async with make_authenticated_client(app, db_path) as client:
        dep_id = (await client.post("/api/dependencies", json={
            "blocker_type": "task", "blocker_id": task_a,
            "blocked_type": "task", "blocked_id": task_b,
        })).json()["id"]

        del_resp = await client.delete(f"/api/dependencies/{dep_id}")
        assert del_resp.status_code == 200
        assert del_resp.json() == {"ok": True}

        get_resp = await client.get(f"/api/task/{task_a}/dependencies")
        assert get_resp.json()["blocks"] == []
