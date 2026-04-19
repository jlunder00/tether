import pytest
from unittest.mock import patch
from db.pg_queries import upsert_anchor, get_anchors

ANCHOR = {
    "id": "grind_am", "name": "The Grind", "time": "08:00",
    "duration_minutes": 120, "flexibility": "locked",
    "strictness": 4, "color": "#e05c5c", "position": 0,
}


@pytest.mark.asyncio
async def test_get_anchors_returns_list(api_client, conn):
    await upsert_anchor(conn, ANCHOR)
    resp = await api_client.get("/api/anchors")
    assert resp.status_code == 200
    assert any(a["id"] == "grind_am" for a in resp.json())


@pytest.mark.asyncio
async def test_put_anchor_updates_time(api_client, conn):
    await upsert_anchor(conn, ANCHOR)
    payload = {"name": "The Grind", "time": "09:00", "duration_minutes": 120,
               "flexibility": "locked", "strictness": 4, "color": "#e05c5c", "position": 0}
    with patch("api.routes.anchors.sync_crontab"):
        resp = await api_client.put("/api/anchors/grind_am", json=payload)
    assert resp.status_code == 200
    anchors = await get_anchors(conn)
    grind = next(a for a in anchors if a["id"] == "grind_am")
    assert grind["time"] == "09:00"


@pytest.mark.asyncio
async def test_put_anchor_calls_sync_crontab(api_client, conn):
    await upsert_anchor(conn, ANCHOR)
    payload = {"name": "The Grind", "time": "09:00", "duration_minutes": 120,
               "flexibility": "locked", "strictness": 4, "color": "#e05c5c", "position": 0}
    with patch("api.routes.anchors.sync_crontab") as mock_sync:
        await api_client.put("/api/anchors/grind_am", json=payload)
    mock_sync.assert_called_once()
