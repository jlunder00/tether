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
def task_uuid(db_path):
    tasks = upsert_tasks(db_path, str(date.today()), "grind_am", [{"text": "Main task"}], notes="")
    return tasks[0]["id"]


@pytest.mark.asyncio
async def test_create_and_list_subtasks(app, db_path, task_uuid):
    async with make_authenticated_client(app, db_path) as client:
        resp = await client.post(f"/api/tasks/{task_uuid}/subtasks", json={"text": "Sub A", "position": 0})
        assert resp.status_code == 200
        created = resp.json()
        assert created["text"] == "Sub A"
        assert created["done"] == 0

        resp2 = await client.post(f"/api/tasks/{task_uuid}/subtasks", json={"text": "Sub B", "position": 1})
        assert resp2.status_code == 200

        list_resp = await client.get(f"/api/tasks/{task_uuid}/subtasks")
        assert list_resp.status_code == 200
        items = list_resp.json()
        assert len(items) == 2
        assert items[0]["text"] == "Sub A"
        assert items[1]["text"] == "Sub B"


@pytest.mark.asyncio
async def test_update_subtask(app, db_path, task_uuid):
    async with make_authenticated_client(app, db_path) as client:
        sub_id = (await client.post(f"/api/tasks/{task_uuid}/subtasks", json={"text": "Draft"})).json()["id"]
        patch_resp = await client.patch(f"/api/tasks/{task_uuid}/subtasks/{sub_id}", json={"text": "Updated", "done": 1})
        assert patch_resp.status_code == 200
        assert patch_resp.json() == {"ok": True}

        items = (await client.get(f"/api/tasks/{task_uuid}/subtasks")).json()
        assert items[0]["text"] == "Updated"
        assert items[0]["done"] == 1


@pytest.mark.asyncio
async def test_delete_subtask(app, db_path, task_uuid):
    async with make_authenticated_client(app, db_path) as client:
        sub_id = (await client.post(f"/api/tasks/{task_uuid}/subtasks", json={"text": "To Delete"})).json()["id"]
        del_resp = await client.delete(f"/api/tasks/{task_uuid}/subtasks/{sub_id}")
        assert del_resp.status_code == 200
        assert del_resp.json() == {"ok": True}

        items = (await client.get(f"/api/tasks/{task_uuid}/subtasks")).json()
        assert items == []


@pytest.mark.asyncio
async def test_reorder_subtasks(app, db_path, task_uuid):
    async with make_authenticated_client(app, db_path) as client:
        id_a = (await client.post(f"/api/tasks/{task_uuid}/subtasks", json={"text": "A", "position": 0})).json()["id"]
        id_b = (await client.post(f"/api/tasks/{task_uuid}/subtasks", json={"text": "B", "position": 1})).json()["id"]

        reorder_resp = await client.put(f"/api/tasks/{task_uuid}/subtasks/reorder", json={"id_order": [id_b, id_a]})
        assert reorder_resp.status_code == 200
        assert reorder_resp.json() == {"ok": True}

        items = (await client.get(f"/api/tasks/{task_uuid}/subtasks")).json()
        # After reorder: id_b should be position 0, id_a should be position 1
        assert items[0]["id"] == id_b
        assert items[1]["id"] == id_a
