"""Tests for bot/anchor_trigger — mocked DB layer."""
import pytest
from contextlib import asynccontextmanager
from unittest.mock import patch, AsyncMock
from bot.anchor_trigger import trigger_anchor
from bot.plan_reader import DayPlan, AnchorPlan

ANCHOR_ID = "00000000-0000-0000-0000-000000000010"


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
    """Build mock pool + get_conn context manager that returns anchors_list."""
    mock_pool = AsyncMock()
    mock_pool.close = AsyncMock()
    mock_conn = AsyncMock()
    mock_conn.get_anchors = AsyncMock(return_value=anchors_list)

    @asynccontextmanager
    async def mock_get_conn(pool, user_id=None):
        yield mock_conn

    return mock_pool, mock_get_conn, mock_conn


@pytest.fixture
def config_dir(tmp_path):
    import yaml
    (tmp_path / "config.yaml").write_text(yaml.dump({
        "telegram": {"bot_token": "test-token", "chat_id": "12345"},
    }))
    return tmp_path


@pytest.mark.asyncio
async def test_trigger_calls_claude_with_anchor_name(config_dir, monkeypatch):
    monkeypatch.setenv("TETHER_USER_ID", "00000000-0000-0000-0000-000000000001")
    mock_pool, mock_get_conn, _ = _make_mock_pool([
        {"id": ANCHOR_ID, "name": "The Grind"},
    ])
    with patch("db.postgres.create_pool", AsyncMock(return_value=mock_pool)), \
         patch("db.postgres.get_conn", mock_get_conn), \
         patch("db.pg_queries.anchors.get_anchors", AsyncMock(return_value=[{"id": ANCHOR_ID, "name": "The Grind"}])), \
         patch("bot.anchor_trigger.load_plan", AsyncMock(return_value=_make_plan(True))), \
         patch("bot.anchor_trigger.load_context", AsyncMock(return_value="")), \
         patch("bot.anchor_trigger.CONFIG_DIR", config_dir), \
         patch("bot.anchor_trigger.call_claude", return_value="Time to grind!") as mock_claude, \
         patch("bot.anchor_trigger.send_telegram"):
        await trigger_anchor(ANCHOR_ID)
    mock_claude.assert_called_once()
    assert "The Grind" in mock_claude.call_args[0][0]


@pytest.mark.asyncio
async def test_trigger_calls_claude_with_tasks(config_dir, monkeypatch):
    monkeypatch.setenv("TETHER_USER_ID", "00000000-0000-0000-0000-000000000001")
    mock_pool, mock_get_conn, _ = _make_mock_pool([])
    with patch("db.postgres.create_pool", AsyncMock(return_value=mock_pool)), \
         patch("db.postgres.get_conn", mock_get_conn), \
         patch("db.pg_queries.anchors.get_anchors", AsyncMock(return_value=[{"id": ANCHOR_ID, "name": "The Grind"}])), \
         patch("bot.anchor_trigger.load_plan", AsyncMock(return_value=_make_plan(True))), \
         patch("bot.anchor_trigger.load_context", AsyncMock(return_value="")), \
         patch("bot.anchor_trigger.CONFIG_DIR", config_dir), \
         patch("bot.anchor_trigger.call_claude", return_value="Go!") as mock_claude, \
         patch("bot.anchor_trigger.send_telegram"):
        await trigger_anchor(ANCHOR_ID)
    assert "Apply to 3 jobs" in mock_claude.call_args[0][0]


@pytest.mark.asyncio
async def test_trigger_sends_claude_response_to_telegram(config_dir, monkeypatch):
    monkeypatch.setenv("TETHER_USER_ID", "00000000-0000-0000-0000-000000000001")
    mock_pool, mock_get_conn, _ = _make_mock_pool([])
    with patch("db.postgres.create_pool", AsyncMock(return_value=mock_pool)), \
         patch("db.postgres.get_conn", mock_get_conn), \
         patch("db.pg_queries.anchors.get_anchors", AsyncMock(return_value=[{"id": ANCHOR_ID, "name": "The Grind"}])), \
         patch("bot.anchor_trigger.load_plan", AsyncMock(return_value=_make_plan(True))), \
         patch("bot.anchor_trigger.load_context", AsyncMock(return_value="")), \
         patch("bot.anchor_trigger.CONFIG_DIR", config_dir), \
         patch("bot.anchor_trigger.call_claude", return_value="Time to grind!"), \
         patch("bot.anchor_trigger.send_telegram") as mock_tg:
        await trigger_anchor(ANCHOR_ID)
    mock_tg.assert_called_once_with(
        bot_token="test-token",
        chat_id="12345",
        text="Time to grind!",
    )


@pytest.mark.asyncio
async def test_trigger_skips_silently_when_anchor_not_in_plan(config_dir, monkeypatch):
    monkeypatch.setenv("TETHER_USER_ID", "00000000-0000-0000-0000-000000000001")
    mock_pool, mock_get_conn, _ = _make_mock_pool([])
    with patch("db.postgres.create_pool", AsyncMock(return_value=mock_pool)), \
         patch("db.postgres.get_conn", mock_get_conn), \
         patch("db.pg_queries.anchors.get_anchors", AsyncMock(return_value=[{"id": ANCHOR_ID, "name": "The Grind"}])), \
         patch("bot.anchor_trigger.load_plan", AsyncMock(return_value=_make_plan(False))), \
         patch("bot.anchor_trigger.load_context", AsyncMock(return_value="")), \
         patch("bot.anchor_trigger.CONFIG_DIR", config_dir), \
         patch("bot.anchor_trigger.call_claude") as mock_claude, \
         patch("bot.anchor_trigger.send_telegram") as mock_tg:
        await trigger_anchor(ANCHOR_ID)
    mock_claude.assert_not_called()
    mock_tg.assert_not_called()


@pytest.mark.asyncio
async def test_trigger_exits_nonzero_for_unknown_anchor(monkeypatch):
    monkeypatch.setenv("TETHER_USER_ID", "00000000-0000-0000-0000-000000000001")
    mock_pool, mock_get_conn, _ = _make_mock_pool([])
    with patch("db.postgres.create_pool", AsyncMock(return_value=mock_pool)), \
         patch("db.postgres.get_conn", mock_get_conn), \
         patch("db.pg_queries.anchors.get_anchors", AsyncMock(return_value=[])):  # empty DB
        with pytest.raises(SystemExit) as exc:
            await trigger_anchor("not_a_real_anchor")
    assert exc.value.code != 0
