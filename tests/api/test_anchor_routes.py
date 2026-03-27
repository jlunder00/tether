import pytest
from unittest.mock import patch
from httpx import AsyncClient, ASGITransport
from db.schema import init_db
from db.queries import upsert_anchor, get_anchors
from api.main import create_app


@pytest.fixture
def db_path(tmp_path):
    path = tmp_path / "tether.db"
    init_db(path)
    upsert_anchor(path, {"id": "grind_am", "name": "The Grind", "time": "08:00",
                          "duration_minutes": 120, "flexibility": "locked",
                          "strictness": 4, "color": "#e05c5c", "position": 0})
    return path


@pytest.fixture
def app(db_path):
    return create_app(db_path)


@pytest.mark.asyncio
async def test_get_anchors_returns_list(app, db_path):
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        resp = await client.get("/api/anchors")
    assert resp.status_code == 200
    assert any(a["id"] == "grind_am" for a in resp.json())


@pytest.mark.asyncio
async def test_put_anchor_updates_time(app, db_path):
    payload = {"name": "The Grind", "time": "09:00", "duration_minutes": 120,
               "flexibility": "locked", "strictness": 4, "color": "#e05c5c", "position": 0}
    with patch("api.routes.anchors.sync_crontab"):
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
            resp = await client.put("/api/anchors/grind_am", json=payload)
    assert resp.status_code == 200
    anchors = get_anchors(db_path)
    grind = next(a for a in anchors if a["id"] == "grind_am")
    assert grind["time"] == "09:00"


@pytest.mark.asyncio
async def test_put_anchor_calls_sync_crontab(app, db_path):
    payload = {"name": "The Grind", "time": "09:00", "duration_minutes": 120,
               "flexibility": "locked", "strictness": 4, "color": "#e05c5c", "position": 0}
    with patch("api.routes.anchors.sync_crontab") as mock_sync:
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
            await client.put("/api/anchors/grind_am", json=payload)
    mock_sync.assert_called_once()
