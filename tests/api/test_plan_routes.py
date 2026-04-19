import pytest
from datetime import date
from db.pg_queries import upsert_anchor, upsert_plan, upsert_tasks, get_plan

ANCHOR_ID = "00000000-0000-0000-0000-000000000010"
ANCHOR = {
    "id": ANCHOR_ID, "name": "The Grind", "time": "08:00",
    "duration_minutes": 120, "flexibility": "locked",
    "strictness": 4, "color": "#e05c5c", "position": 0,
}


@pytest.mark.asyncio
async def test_get_plan_returns_date(api_client, conn):
    await upsert_anchor(conn, ANCHOR)
    await upsert_plan(conn, str(date.today()))
    await upsert_tasks(conn, str(date.today()), ANCHOR_ID, tasks=["Apply to jobs"], notes="ML roles")
    resp = await api_client.get(f"/api/plan/{date.today()}")
    assert resp.status_code == 200
    assert resp.json()["date"] == str(date.today())


@pytest.mark.asyncio
async def test_get_plan_returns_anchors(api_client, conn):
    await upsert_anchor(conn, ANCHOR)
    await upsert_plan(conn, str(date.today()))
    await upsert_tasks(conn, str(date.today()), ANCHOR_ID, tasks=["Apply to jobs"], notes="ML roles")
    resp = await api_client.get(f"/api/plan/{date.today()}")
    assert ANCHOR_ID in resp.json()["anchors"]


@pytest.mark.asyncio
async def test_put_anchor_tasks_updates_db(api_client, conn):
    await upsert_anchor(conn, ANCHOR)
    await upsert_plan(conn, str(date.today()))
    resp = await api_client.put(
        f"/api/plan/{date.today()}/anchors/{ANCHOR_ID}",
        json={"tasks": ["Updated task"], "notes": ""}
    )
    assert resp.status_code == 200
    plan = await get_plan(conn, str(date.today()))
    texts = [t["text"] for t in plan["anchors"][ANCHOR_ID]["tasks"]]
    assert "Updated task" in texts


@pytest.mark.asyncio
async def test_get_anchors(api_client, conn):
    await upsert_anchor(conn, ANCHOR)
    resp = await api_client.get("/api/anchors")
    assert resp.status_code == 200
    assert any(a["id"] == ANCHOR_ID for a in resp.json())


@pytest.mark.asyncio
async def test_put_anchor_tasks_returns_task_objects(api_client, conn):
    await upsert_anchor(conn, ANCHOR)
    await upsert_plan(conn, str(date.today()))
    resp = await api_client.put(
        f"/api/plan/{date.today()}/anchors/{ANCHOR_ID}",
        json={"tasks": [{"text": "New task", "status": "pending"}], "notes": ""}
    )
    assert resp.status_code == 200
    data = resp.json()
    assert data["ok"] is True
    assert len(data["tasks"]) >= 1
    new_task = next(t for t in data["tasks"] if t["text"] == "New task")
    assert len(new_task["id"]) == 36


@pytest.mark.asyncio
async def test_get_plan_returns_task_objects_with_status(api_client, conn):
    await upsert_anchor(conn, ANCHOR)
    await upsert_plan(conn, str(date.today()))
    await upsert_tasks(conn, str(date.today()), ANCHOR_ID, tasks=["Apply to jobs"], notes="ML roles")
    resp = await api_client.get(f"/api/plan/{date.today()}")
    task = resp.json()["anchors"][ANCHOR_ID]["tasks"][0]
    assert isinstance(task, dict)
    assert "id" in task and "status" in task


@pytest.mark.asyncio
async def test_patch_task_status(api_client, conn):
    await upsert_anchor(conn, ANCHOR)
    await upsert_plan(conn, str(date.today()))
    put_resp = await api_client.put(
        f"/api/plan/{date.today()}/anchors/{ANCHOR_ID}",
        json={"tasks": [{"text": "Task"}], "notes": ""}
    )
    task_id = put_resp.json()["tasks"][0]["id"]
    resp = await api_client.patch(f"/api/tasks/{task_id}", json={"status": "in_progress"})
    assert resp.status_code == 200
    assert resp.json()["status"] == "in_progress"


@pytest.mark.asyncio
async def test_patch_task_not_found(api_client, conn):
    resp = await api_client.patch("/api/tasks/00000000-0000-0000-0000-000000000000", json={"status": "done"})
    assert resp.status_code == 404


@pytest.mark.asyncio
async def test_move_task(api_client, conn):
    from datetime import timedelta
    today = str(date.today())
    tomorrow = str(date.today() + timedelta(days=1))
    await upsert_anchor(conn, ANCHOR)
    await upsert_plan(conn, today)
    put_resp = await api_client.put(
        f"/api/plan/{today}/anchors/{ANCHOR_ID}",
        json={"tasks": [{"text": "Move me"}], "notes": ""}
    )
    task_id = put_resp.json()["tasks"][0]["id"]
    resp = await api_client.put(
        f"/api/tasks/{task_id}/move",
        json={"date": tomorrow, "anchor_id": ANCHOR_ID}
    )
    assert resp.status_code == 200
    assert resp.json()["ok"] is True


@pytest.mark.asyncio
async def test_get_plan_range_returns_dict_of_day_plans(api_client, conn):
    from datetime import date, timedelta
    today = str(date.today())
    tomorrow = str(date.today() + timedelta(days=1))
    await upsert_anchor(conn, ANCHOR)
    await upsert_plan(conn, today)
    resp = await api_client.get(f"/api/plan/range?start={today}&end={tomorrow}")
    assert resp.status_code == 200
    data = resp.json()
    assert today in data
    assert tomorrow in data
    assert "anchors" in data[today]
