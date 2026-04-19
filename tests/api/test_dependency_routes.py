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
async def two_tasks(conn):
    await upsert_anchor(conn, ANCHOR)
    await upsert_plan(conn, str(date.today()))
    tasks = await upsert_tasks(conn, str(date.today()), ANCHOR_ID,
                               [{"text": "Task 1"}, {"text": "Task 2"}], notes="")
    return tasks[0]["id"], tasks[1]["id"]


@pytest.mark.asyncio
async def test_create_and_get_dependency(api_client, conn, two_tasks):
    task_a, task_b = two_tasks
    resp = await api_client.post("/api/dependencies", json={
        "blocker_type": "task", "blocker_id": task_a,
        "blocked_type": "task", "blocked_id": task_b,
    })
    assert resp.status_code == 200
    dep_id = resp.json()["id"]
    assert isinstance(dep_id, int)

    # task_a blocks task_b — get deps for task_a
    get_resp = await api_client.get(f"/api/task/{task_a}/dependencies")
    assert get_resp.status_code == 200
    data = get_resp.json()
    assert len(data["blocks"]) == 1
    assert data["blocks"][0]["entity_id"] == task_b
    assert data["blocked_by"] == []

    # get deps for task_b
    get_resp2 = await api_client.get(f"/api/task/{task_b}/dependencies")
    assert get_resp2.status_code == 200
    data2 = get_resp2.json()
    assert data2["blocks"] == []
    assert len(data2["blocked_by"]) == 1
    assert data2["blocked_by"][0]["entity_id"] == task_a


@pytest.mark.asyncio
async def test_delete_dependency(api_client, conn, two_tasks):
    task_a, task_b = two_tasks
    dep_id = (await api_client.post("/api/dependencies", json={
        "blocker_type": "task", "blocker_id": task_a,
        "blocked_type": "task", "blocked_id": task_b,
    })).json()["id"]

    del_resp = await api_client.delete(f"/api/dependencies/{dep_id}")
    assert del_resp.status_code == 200
    assert del_resp.json() == {"ok": True}

    get_resp = await api_client.get(f"/api/task/{task_a}/dependencies")
    assert get_resp.json()["blocks"] == []
