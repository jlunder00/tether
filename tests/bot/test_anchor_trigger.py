"""Tests for bot/anchor_trigger — mocked DB layer.

Updated for Phase 1 per-user Telegram migration:
  - trigger_anchor(pool, user_id, dispatch_fn, anchor_id) new signature
  - dispatch_fn replaces send_telegram() — caller controls how message is sent
  - call_claude imported from bot.message_handler (async, agent SDK)
  - No TETHER_USER_ID env var, no config.yaml, no send_telegram
"""
import pytest
from contextlib import asynccontextmanager
from unittest.mock import patch, AsyncMock, MagicMock
from bot.anchor_trigger import trigger_anchor
from bot.plan_reader import DayPlan, AnchorPlan

ANCHOR_ID = "00000000-0000-0000-0000-000000000010"
USER_ID = "00000000-0000-0000-0000-000000000001"


def _make_plan(has_anchor: bool) -> DayPlan:
    anchors = {}
    if has_anchor:
        anchors[ANCHOR_ID] = AnchorPlan(tasks=[{"text": "Apply to 3 jobs"}], notes="ML roles")
    return DayPlan(
        date="2026-03-25",
        anchors=anchors,
        acknowledgements={},
        check_in_log=[],
    )


def _make_mock_pool(anchors_list):
    """Build mock pool + get_conn context manager."""
    mock_pool = AsyncMock()
    mock_pool.close = AsyncMock()
    mock_conn = AsyncMock()

    @asynccontextmanager
    async def mock_get_conn(pool, user_id=None):
        yield mock_conn

    return mock_pool, mock_get_conn, mock_conn


@pytest.mark.asyncio
async def test_trigger_calls_claude_with_anchor_name():
    mock_pool, mock_get_conn, _ = _make_mock_pool([
        {"id": ANCHOR_ID, "name": "The Grind"},
    ])
    dispatched: list[str] = []

    async def dispatch(msg: str) -> None:
        dispatched.append(msg)

    with patch("db.postgres.get_conn", mock_get_conn), \
         patch("db.pg_queries.anchors.get_anchors", AsyncMock(return_value=[{"id": ANCHOR_ID, "name": "The Grind"}])), \
         patch("bot.anchor_trigger.load_plan", AsyncMock(return_value=_make_plan(True))), \
         patch("bot.anchor_trigger.load_context", AsyncMock(return_value="")), \
         patch("bot.anchor_trigger.call_claude", AsyncMock(return_value="Time to grind!")) as mock_claude:
        await trigger_anchor(mock_pool, USER_ID, dispatch, ANCHOR_ID)

    mock_claude.assert_called_once()
    assert "The Grind" in mock_claude.call_args[0][0]


@pytest.mark.asyncio
async def test_trigger_calls_claude_with_tasks():
    mock_pool, mock_get_conn, _ = _make_mock_pool([])
    dispatched: list[str] = []

    async def dispatch(msg: str) -> None:
        dispatched.append(msg)

    with patch("db.postgres.get_conn", mock_get_conn), \
         patch("db.pg_queries.anchors.get_anchors", AsyncMock(return_value=[{"id": ANCHOR_ID, "name": "The Grind"}])), \
         patch("bot.anchor_trigger.load_plan", AsyncMock(return_value=_make_plan(True))), \
         patch("bot.anchor_trigger.load_context", AsyncMock(return_value="")), \
         patch("bot.anchor_trigger.call_claude", AsyncMock(return_value="Go!")) as mock_claude:
        await trigger_anchor(mock_pool, USER_ID, dispatch, ANCHOR_ID)

    assert "Apply to 3 jobs" in mock_claude.call_args[0][0]


@pytest.mark.asyncio
async def test_trigger_dispatches_claude_response_via_dispatch_fn():
    mock_pool, mock_get_conn, _ = _make_mock_pool([])
    dispatched: list[str] = []

    async def dispatch(msg: str) -> None:
        dispatched.append(msg)

    with patch("db.postgres.get_conn", mock_get_conn), \
         patch("db.pg_queries.anchors.get_anchors", AsyncMock(return_value=[{"id": ANCHOR_ID, "name": "The Grind"}])), \
         patch("bot.anchor_trigger.load_plan", AsyncMock(return_value=_make_plan(True))), \
         patch("bot.anchor_trigger.load_context", AsyncMock(return_value="")), \
         patch("bot.anchor_trigger.call_claude", AsyncMock(return_value="Time to grind!")):
        await trigger_anchor(mock_pool, USER_ID, dispatch, ANCHOR_ID)

    assert dispatched == ["Time to grind!"]


@pytest.mark.asyncio
async def test_trigger_skips_silently_when_anchor_not_in_plan():
    mock_pool, mock_get_conn, _ = _make_mock_pool([])

    async def dispatch(msg: str) -> None:
        raise AssertionError(f"dispatch should not be called: {msg}")

    with patch("db.postgres.get_conn", mock_get_conn), \
         patch("db.pg_queries.anchors.get_anchors", AsyncMock(return_value=[{"id": ANCHOR_ID, "name": "The Grind"}])), \
         patch("bot.anchor_trigger.load_plan", AsyncMock(return_value=_make_plan(False))), \
         patch("bot.anchor_trigger.load_context", AsyncMock(return_value="")), \
         patch("bot.anchor_trigger.call_claude", AsyncMock()) as mock_claude:
        await trigger_anchor(mock_pool, USER_ID, dispatch, ANCHOR_ID)

    mock_claude.assert_not_called()


@pytest.mark.asyncio
async def test_trigger_returns_silently_for_unknown_anchor():
    """Unknown anchor_id logs an error and returns without raising or dispatching."""
    mock_pool, mock_get_conn, _ = _make_mock_pool([])

    async def dispatch(msg: str) -> None:
        raise AssertionError(f"dispatch should not be called: {msg}")

    with patch("db.postgres.get_conn", mock_get_conn), \
         patch("db.pg_queries.anchors.get_anchors", AsyncMock(return_value=[])), \
         patch("bot.anchor_trigger.load_plan", AsyncMock(return_value=_make_plan(False))), \
         patch("bot.anchor_trigger.load_context", AsyncMock(return_value="")):
        # Should not raise — just logs error and returns
        await trigger_anchor(mock_pool, USER_ID, dispatch, "not_a_real_anchor")
