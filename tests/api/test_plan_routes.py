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
    assert plan["anchors"]["grind_am"]["tasks"] == ["Updated task"]


@pytest.mark.asyncio
async def test_get_anchors(app):
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        resp = await client.get("/api/anchors")
    assert resp.status_code == 200
    assert any(a["id"] == "grind_am" for a in resp.json())
