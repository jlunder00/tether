import pytest
from datetime import date
from db.pg_queries import upsert_anchor, upsert_plan, upsert_tasks

ANCHOR_ID = "00000000-0000-0000-0000-000000000010"
ANCHOR = {
    "id": ANCHOR_ID, "name": "The Grind", "time": "08:00",
    "duration_minutes": 120, "flexibility": "locked",
    "strictness": 4, "color": "#e05c5c", "position": 1,
}


@pytest.fixture
async def task_uuid(conn):
    await upsert_anchor(conn, ANCHOR)
    await upsert_plan(conn, str(date.today()))
    tasks = await upsert_tasks(conn, str(date.today()), ANCHOR_ID, [{"text": "Main task"}], notes="")
    return tasks[0]["id"]


@pytest.mark.asyncio
async def test_create_and_list_subtasks(api_client, conn, task_uuid):
    resp = await api_client.post(f"/api/tasks/{task_uuid}/subtasks", json={"text": "Sub A", "position": 0})
    assert resp.status_code == 200
    created = resp.json()
    assert created["text"] == "Sub A"
    assert created["done"] == 0

    resp2 = await api_client.post(f"/api/tasks/{task_uuid}/subtasks", json={"text": "Sub B", "position": 1})
    assert resp2.status_code == 200

    list_resp = await api_client.get(f"/api/tasks/{task_uuid}/subtasks")
    assert list_resp.status_code == 200
    items = list_resp.json()
    assert len(items) == 2
    assert items[0]["text"] == "Sub A"
    assert items[1]["text"] == "Sub B"


@pytest.mark.asyncio
async def test_update_subtask(api_client, conn, task_uuid):
    sub_id = (await api_client.post(f"/api/tasks/{task_uuid}/subtasks", json={"text": "Draft"})).json()["id"]
    patch_resp = await api_client.patch(f"/api/tasks/{task_uuid}/subtasks/{sub_id}", json={"text": "Updated", "done": 1})
    assert patch_resp.status_code == 200
    assert patch_resp.json() == {"ok": True}

    items = (await api_client.get(f"/api/tasks/{task_uuid}/subtasks")).json()
    assert items[0]["text"] == "Updated"
    assert items[0]["done"] == 1


@pytest.mark.asyncio
async def test_delete_subtask(api_client, conn, task_uuid):
    sub_id = (await api_client.post(f"/api/tasks/{task_uuid}/subtasks", json={"text": "To Delete"})).json()["id"]
    del_resp = await api_client.delete(f"/api/tasks/{task_uuid}/subtasks/{sub_id}")
    assert del_resp.status_code == 200
    assert del_resp.json() == {"ok": True}

    items = (await api_client.get(f"/api/tasks/{task_uuid}/subtasks")).json()
    assert items == []


@pytest.mark.asyncio
async def test_reorder_subtasks(api_client, conn, task_uuid):
    id_a = (await api_client.post(f"/api/tasks/{task_uuid}/subtasks", json={"text": "A", "position": 0})).json()["id"]
    id_b = (await api_client.post(f"/api/tasks/{task_uuid}/subtasks", json={"text": "B", "position": 1})).json()["id"]

    reorder_resp = await api_client.put(f"/api/tasks/{task_uuid}/subtasks/reorder", json={"id_order": [id_b, id_a]})
    assert reorder_resp.status_code == 200
    assert reorder_resp.json() == {"ok": True}

    items = (await api_client.get(f"/api/tasks/{task_uuid}/subtasks")).json()
    assert items[0]["id"] == id_b
    assert items[1]["id"] == id_a
