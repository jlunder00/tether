"""Tests for api.routes.anchors._refresh_anchor_due_cache — the anchor-CRUD
side of the Redis next-due gating scheme (shared/notify_due.py).

Pure unit tests: get_anchors and shared.notify_due are monkeypatched so no
real Postgres/Redis connection is needed.
"""
from __future__ import annotations

from datetime import datetime
from unittest.mock import AsyncMock, MagicMock

import pytest

import api.routes.anchors as anchors_mod

pytestmark = pytest.mark.timeout(30)


async def test_refresh_caches_current_anchor_list(monkeypatch):
    anchors = [{"id": "a", "time": "09:00", "duration_minutes": 30}]
    monkeypatch.setattr(anchors_mod, "get_anchors", AsyncMock(return_value=anchors))
    set_cached = AsyncMock()
    monkeypatch.setattr(anchors_mod.notify_due, "set_cached_anchors", set_cached)
    monkeypatch.setattr(
        anchors_mod.notify_due, "next_anchor_boundary", MagicMock(return_value=None)
    )

    await anchors_mod._refresh_anchor_due_cache(conn=object(), user_id="u1")

    set_cached.assert_awaited_once_with("u1", anchors)


async def test_refresh_writes_anchor_component_when_boundary_exists(monkeypatch):
    anchors = [{"id": "a", "time": "09:00", "duration_minutes": 30}]
    boundary = datetime(2026, 6, 15, 9, 0)
    monkeypatch.setattr(anchors_mod, "get_anchors", AsyncMock(return_value=anchors))
    monkeypatch.setattr(anchors_mod.notify_due, "set_cached_anchors", AsyncMock())
    monkeypatch.setattr(
        anchors_mod.notify_due, "next_anchor_boundary", MagicMock(return_value=boundary)
    )
    set_component_due = AsyncMock()
    monkeypatch.setattr(anchors_mod.notify_due, "set_component_due", set_component_due)

    await anchors_mod._refresh_anchor_due_cache(conn=object(), user_id="u1")

    set_component_due.assert_awaited_once_with("u1", "anchor", boundary.timestamp())


async def test_refresh_skips_component_write_when_no_anchors(monkeypatch):
    """No anchors configured at all — nothing to write for the anchor
    component (it simply stays absent from the combined score)."""
    monkeypatch.setattr(anchors_mod, "get_anchors", AsyncMock(return_value=[]))
    monkeypatch.setattr(anchors_mod.notify_due, "set_cached_anchors", AsyncMock())
    monkeypatch.setattr(
        anchors_mod.notify_due, "next_anchor_boundary", MagicMock(return_value=None)
    )
    set_component_due = AsyncMock()
    monkeypatch.setattr(anchors_mod.notify_due, "set_component_due", set_component_due)

    await anchors_mod._refresh_anchor_due_cache(conn=object(), user_id="u1")

    set_component_due.assert_not_called()


async def test_refresh_swallows_get_anchors_failure_without_raising(monkeypatch):
    """CRITICAL contract: this helper runs AFTER the real anchor mutation has
    already committed (see call sites in create_anchor/update_anchor/
    delete_anchor_route). A failure re-reading anchors for the cache must
    never propagate and turn an already-successful mutation into a 500, and
    must never prevent the caller's subsequent `anchors_updated` WS
    broadcast from running."""
    monkeypatch.setattr(
        anchors_mod, "get_anchors", AsyncMock(side_effect=RuntimeError("db blip"))
    )
    set_cached = AsyncMock()
    monkeypatch.setattr(anchors_mod.notify_due, "set_cached_anchors", set_cached)

    await anchors_mod._refresh_anchor_due_cache(conn=object(), user_id="u1")  # must not raise

    set_cached.assert_not_called()
