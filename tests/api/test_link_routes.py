import pytest
from datetime import date
from db.pg_queries import upsert_anchor, upsert_plan, upsert_tasks

ANCHOR = {
    "id": "grind_am", "name": "The Grind", "time": "08:00",
    "duration_minutes": 120, "flexibility": "locked",
    "strictness": 4, "color": "#e05c5c", "position": 1,
}


@pytest.fixture
async def task_uuid(conn):
    await upsert_anchor(conn, ANCHOR)
    await upsert_plan(conn, str(date.today()))
    tasks = await upsert_tasks(conn, str(date.today()), "grind_am", [{"text": "Linked task"}], notes="")
    return tasks[0]["id"]


@pytest.mark.asyncio
async def test_create_and_list_links(api_client, conn, task_uuid):
    resp = await api_client.post(f"/api/task/{task_uuid}/links", json={
        "url": "https://example.com",
        "label": "Example",
        "category": "reference",
    })
    assert resp.status_code == 200
    link = resp.json()
    assert link["url"] == "https://example.com"
    assert link["label"] == "Example"
    assert link["category"] == "reference"

    resp2 = await api_client.post(f"/api/task/{task_uuid}/links", json={
        "url": "https://docs.example.com",
    })
    assert resp2.status_code == 200
    assert resp2.json()["category"] == "other"

    list_resp = await api_client.get(f"/api/task/{task_uuid}/links")
    assert list_resp.status_code == 200
    items = list_resp.json()
    assert len(items) == 2
    assert items[0]["url"] == "https://example.com"
    assert items[1]["url"] == "https://docs.example.com"


@pytest.mark.asyncio
async def test_delete_link(api_client, conn, task_uuid):
    link_id = (await api_client.post(f"/api/task/{task_uuid}/links", json={
        "url": "https://to-delete.com",
    })).json()["id"]

    del_resp = await api_client.delete(f"/api/links/{link_id}")
    assert del_resp.status_code == 200
    assert del_resp.json() == {"ok": True}

    items = (await api_client.get(f"/api/task/{task_uuid}/links")).json()
    assert items == []
