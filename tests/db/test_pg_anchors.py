"""Tests for db/pg_queries/anchors.py"""
import pytest
import uuid

from tests.db.pg_conftest import conn, TEST_USER_ID  # noqa: F401
from db.pg_queries.anchors import (
    get_anchors, upsert_anchor, patch_anchor, delete_anchor, seed_default_anchors,
)


@pytest.mark.asyncio
async def test_seed_and_get_anchors(conn):
    await seed_default_anchors(conn, TEST_USER_ID)
    anchors = await get_anchors(conn)
    assert len(anchors) > 0
    assert all("id" in a for a in anchors)
    assert all("name" in a for a in anchors)


@pytest.mark.asyncio
async def test_upsert_anchor(conn):
    anchor_id = str(uuid.uuid4())
    await upsert_anchor(conn, {
        "id": anchor_id,
        "name": "Deep Work",
        "time": "09:00",
        "duration_minutes": 120,
        "flexibility": "strict",
        "strictness": 5,
        "color": "#0000ff",
        "position": 0,
        "followup_config": {"enabled": False},
    })
    anchors = await get_anchors(conn)
    ids = [a["id"] for a in anchors]
    assert anchor_id in ids


@pytest.mark.asyncio
async def test_patch_anchor(conn):
    anchor_id = str(uuid.uuid4())
    await upsert_anchor(conn, {
        "id": anchor_id,
        "name": "Morning",
        "time": "08:00",
        "duration_minutes": 60,
        "flexibility": "flexible",
        "strictness": 3,
        "color": "#aaaaaa",
        "position": 1,
    })
    await patch_anchor(conn, anchor_id, {"name": "Morning Block", "color": "#ff0000"})
    anchors = await get_anchors(conn)
    updated = next(a for a in anchors if a["id"] == anchor_id)
    assert updated["name"] == "Morning Block"
    assert updated["color"] == "#ff0000"


@pytest.mark.asyncio
async def test_delete_anchor(conn):
    anchor_id = str(uuid.uuid4())
    await upsert_anchor(conn, {
        "id": anchor_id,
        "name": "Temp",
        "time": "12:00",
        "duration_minutes": 30,
        "flexibility": "flexible",
        "strictness": 1,
        "color": "#cccccc",
        "position": 99,
    })
    await delete_anchor(conn, anchor_id)
    anchors = await get_anchors(conn)
    assert anchor_id not in [a["id"] for a in anchors]
