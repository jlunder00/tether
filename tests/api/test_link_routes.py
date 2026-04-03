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
    tasks = upsert_tasks(db_path, str(date.today()), "grind_am", [{"text": "Linked task"}], notes="")
    return tasks[0]["id"]


@pytest.mark.asyncio
async def test_create_and_list_links(app, db_path, task_uuid):
    async with make_authenticated_client(app, db_path) as client:
        resp = await client.post(f"/api/task/{task_uuid}/links", json={
            "url": "https://example.com",
            "label": "Example",
            "category": "reference",
        })
        assert resp.status_code == 200
        link = resp.json()
        assert link["url"] == "https://example.com"
        assert link["label"] == "Example"
        assert link["category"] == "reference"

        resp2 = await client.post(f"/api/task/{task_uuid}/links", json={
            "url": "https://docs.example.com",
        })
        assert resp2.status_code == 200
        assert resp2.json()["category"] == "other"

        list_resp = await client.get(f"/api/task/{task_uuid}/links")
        assert list_resp.status_code == 200
        items = list_resp.json()
        assert len(items) == 2
        assert items[0]["url"] == "https://example.com"
        assert items[1]["url"] == "https://docs.example.com"


@pytest.mark.asyncio
async def test_delete_link(app, db_path, task_uuid):
    async with make_authenticated_client(app, db_path) as client:
        link_id = (await client.post(f"/api/task/{task_uuid}/links", json={
            "url": "https://to-delete.com",
        })).json()["id"]

        del_resp = await client.delete(f"/api/links/{link_id}")
        assert del_resp.status_code == 200
        assert del_resp.json() == {"ok": True}

        items = (await client.get(f"/api/task/{task_uuid}/links")).json()
        assert items == []
