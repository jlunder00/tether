"""Tests for the Redis next-due gating wired into api/routes/internal.py's
_run_notification_check — the core Neon-idle-spin-down fix.

No real Postgres/Redis needed: pool-touching functions and shared.notify_due
are monkeypatched to assert call/no-call behaviour.
"""
from __future__ import annotations

from datetime import datetime
from unittest.mock import AsyncMock, MagicMock

import pytest

import api.routes.internal as internal_mod

pytestmark = pytest.mark.timeout(30)


# ---------------------------------------------------------------------------
# _run_notification_check — outer gate
# ---------------------------------------------------------------------------

async def test_skips_all_postgres_when_nothing_due(monkeypatch):
    """The whole point: when the Redis gate confirms nothing is due, neither
    linked-user-fetch path may touch Postgres at all."""
    monkeypatch.setattr(
        internal_mod.notify_due, "get_due_user_ids", AsyncMock(return_value=[])
    )
    get_all = AsyncMock()
    get_by_id = AsyncMock()
    monkeypatch.setattr(internal_mod, "_get_all_linked_users", get_all)
    monkeypatch.setattr(internal_mod, "_get_linked_users_by_id", get_by_id)

    await internal_mod._run_notification_check(pool=object(), ws_manager=None)

    get_all.assert_not_called()
    get_by_id.assert_not_called()


async def test_falls_back_to_full_scan_when_gating_unavailable(monkeypatch):
    """None (Redis unavailable) must fail OPEN — fall back to the original
    unfiltered behaviour rather than silently skipping everyone."""
    monkeypatch.setattr(
        internal_mod.notify_due, "get_due_user_ids", AsyncMock(return_value=None)
    )
    get_all = AsyncMock(return_value=[])
    get_by_id = AsyncMock()
    monkeypatch.setattr(internal_mod, "_get_all_linked_users", get_all)
    monkeypatch.setattr(internal_mod, "_get_linked_users_by_id", get_by_id)

    await internal_mod._run_notification_check(pool=object(), ws_manager=None)

    get_all.assert_awaited_once()
    get_by_id.assert_not_called()


async def test_scopes_postgres_fetch_to_due_users_only(monkeypatch):
    """When specific users are due, only THOSE users are fetched — never the
    full linked-users table scan."""
    monkeypatch.setattr(
        internal_mod.notify_due, "get_due_user_ids", AsyncMock(return_value=["u1", "u2"])
    )
    get_all = AsyncMock()
    get_by_id = AsyncMock(return_value=[])
    monkeypatch.setattr(internal_mod, "_get_all_linked_users", get_all)
    monkeypatch.setattr(internal_mod, "_get_linked_users_by_id", get_by_id)

    await internal_mod._run_notification_check(pool=object(), ws_manager=None)

    get_all.assert_not_called()
    get_by_id.assert_awaited_once()
    assert get_by_id.await_args.args[1] == ["u1", "u2"]


async def test_recomputes_due_cache_after_processing_each_user(monkeypatch):
    """After the real checks run for a due user, the anchor/followup next-due
    estimates must be written back to Redis (recompute-after-run pattern)."""
    user = {"id": "u1", "telegram_chat_id": "123"}
    anchor_next = datetime(2026, 6, 15, 10, 0)
    followup_next = datetime(2026, 6, 15, 9, 30)

    monkeypatch.setattr(
        internal_mod.notify_due, "get_due_user_ids", AsyncMock(return_value=["u1"])
    )
    monkeypatch.setattr(internal_mod, "_get_linked_users_by_id", AsyncMock(return_value=[user]))
    monkeypatch.setattr(
        internal_mod, "_check_anchor_transitions", AsyncMock(return_value=anchor_next)
    )
    monkeypatch.setattr(internal_mod, "check_followups", AsyncMock(return_value=followup_next))

    set_component_due = AsyncMock()
    monkeypatch.setattr(internal_mod.notify_due, "set_component_due", set_component_due)

    await internal_mod._run_notification_check(pool=object(), ws_manager=None)

    calls = {c.args[1]: c.args[2] for c in set_component_due.await_args_list}
    assert calls["anchor"] == anchor_next.timestamp()
    assert calls["followup"] == followup_next.timestamp()


async def test_no_recompute_write_when_neither_component_present(monkeypatch):
    """If a user has neither anchors nor active followups, nothing is written
    — an absent component simply doesn't contribute to the combined score."""
    user = {"id": "u1", "telegram_chat_id": "123"}
    monkeypatch.setattr(
        internal_mod.notify_due, "get_due_user_ids", AsyncMock(return_value=["u1"])
    )
    monkeypatch.setattr(internal_mod, "_get_linked_users_by_id", AsyncMock(return_value=[user]))
    monkeypatch.setattr(internal_mod, "_check_anchor_transitions", AsyncMock(return_value=None))
    monkeypatch.setattr(internal_mod, "check_followups", AsyncMock(return_value=None))

    set_component_due = AsyncMock()
    monkeypatch.setattr(internal_mod.notify_due, "set_component_due", set_component_due)

    await internal_mod._run_notification_check(pool=object(), ws_manager=None)

    set_component_due.assert_not_called()


# ---------------------------------------------------------------------------
# _check_anchor_transitions — returns anchor component + caches schedule
# ---------------------------------------------------------------------------

async def test_check_anchor_transitions_caches_anchors_and_returns_boundary(monkeypatch):
    anchors = [{"id": "a", "time": "09:00", "duration_minutes": 30}]
    plan: dict = {}
    sentinel_boundary = datetime(2026, 6, 15, 9, 0)

    monkeypatch.setattr(
        "bot.message_handler._get_anchors_and_plan",
        AsyncMock(return_value=(anchors, plan)),
    )
    monkeypatch.setattr("bot.handler_utils.is_anchor_active", lambda a, now=None: False)

    set_cached = AsyncMock()
    monkeypatch.setattr(internal_mod.notify_due, "set_cached_anchors", set_cached)
    monkeypatch.setattr(
        internal_mod.notify_due,
        "next_anchor_boundary",
        MagicMock(return_value=sentinel_boundary),
    )

    result = await internal_mod._check_anchor_transitions(object(), "u1", AsyncMock())

    assert result is sentinel_boundary
    set_cached.assert_awaited_once_with("u1", anchors)


async def test_check_anchor_transitions_returns_none_on_exception(monkeypatch):
    monkeypatch.setattr(
        "bot.message_handler._get_anchors_and_plan",
        AsyncMock(side_effect=RuntimeError("boom")),
    )

    result = await internal_mod._check_anchor_transitions(object(), "u1", AsyncMock())

    assert result is None
