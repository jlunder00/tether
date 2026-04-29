"""Tests for motif field in anchor create/update responses."""
import pytest
from unittest.mock import patch

ANCHOR_BASE = {
    "name": "Focus Block",
    "time": "09:00",
    "duration_minutes": 90,
    "flexibility": "flexible",
    "strictness": 3,
    "color": "#7c6af7",
    "position": 0,
}


@pytest.mark.asyncio
async def test_post_anchor_with_motif(api_client, conn):
    """POST anchor with motif 'focus' → GET returns that anchor with motif == 'focus'."""
    payload = {**ANCHOR_BASE, "motif": "focus"}
    with patch("api.routes.anchors.sync_crontab"):
        resp = await api_client.post("/api/anchors", json=payload)
    assert resp.status_code == 200
    anchor_id = resp.json()["id"]

    resp = await api_client.get("/api/anchors")
    assert resp.status_code == 200
    anchors = resp.json()
    created = next((a for a in anchors if a["id"] == anchor_id), None)
    assert created is not None
    assert created["motif"] == "focus"


@pytest.mark.asyncio
async def test_post_anchor_default_motif(api_client, conn):
    """POST anchor without motif → GET returns anchor with motif == 'anchor' (default)."""
    with patch("api.routes.anchors.sync_crontab"):
        resp = await api_client.post("/api/anchors", json=ANCHOR_BASE)
    assert resp.status_code == 200
    anchor_id = resp.json()["id"]

    resp = await api_client.get("/api/anchors")
    assert resp.status_code == 200
    anchors = resp.json()
    created = next((a for a in anchors if a["id"] == anchor_id), None)
    assert created is not None
    assert created["motif"] == "anchor"


@pytest.mark.asyncio
async def test_put_anchor_updates_motif(api_client, conn):
    """PUT anchor updating motif to 'calm' → GET returns updated motif."""
    with patch("api.routes.anchors.sync_crontab"):
        post_resp = await api_client.post("/api/anchors", json=ANCHOR_BASE)
    assert post_resp.status_code == 200
    anchor_id = post_resp.json()["id"]

    payload = {**ANCHOR_BASE, "motif": "calm"}
    with patch("api.routes.anchors.sync_crontab"):
        put_resp = await api_client.put(f"/api/anchors/{anchor_id}", json=payload)
    assert put_resp.status_code == 200

    resp = await api_client.get("/api/anchors")
    anchors = resp.json()
    updated = next((a for a in anchors if a["id"] == anchor_id), None)
    assert updated is not None
    assert updated["motif"] == "calm"


@pytest.mark.asyncio
async def test_post_anchor_invalid_motif(api_client, conn):
    """POST anchor with invalid motif value → 422 response."""
    payload = {**ANCHOR_BASE, "motif": "unknown"}
    with patch("api.routes.anchors.sync_crontab"):
        resp = await api_client.post("/api/anchors", json=payload)
    assert resp.status_code == 422
