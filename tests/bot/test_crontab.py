"""Tests for bot/crontab — crontab formatting and subprocess wiring."""
import pytest
from contextlib import asynccontextmanager
from unittest.mock import patch, AsyncMock
from bot.crontab import sync_crontab, MARKER_START, MARKER_END

ANCHORS = [
    {"id": "00000000-0000-0000-0000-000000000010", "name": "The Grind", "time": "08:00"},
    {"id": "00000000-0000-0000-0000-000000000011", "name": "Deep Work", "time": "10:30"},
]


async def _run(existing_crontab=""):
    """Run sync_crontab with mocked DB and subprocess; return written crontab."""
    written = []
    mock_pool = AsyncMock()
    mock_conn = AsyncMock()

    @asynccontextmanager
    async def mock_get_conn(pool, user_id=None):
        yield mock_conn

    def fake_run(cmd, **kwargs):
        class R:
            pass
        r = R()
        if cmd == ["crontab", "-l"]:
            r.stdout = existing_crontab
            r.returncode = 0 if existing_crontab else 1
        else:
            written.append(kwargs.get("input", ""))
            r.returncode = 0
        return r

    with patch("bot.crontab.pg.get_conn", mock_get_conn), \
         patch("bot.crontab.get_anchors", AsyncMock(return_value=ANCHORS)), \
         patch("bot.crontab.subprocess.run", side_effect=fake_run):
        await sync_crontab(mock_pool, "00000000-0000-0000-0000-000000000001")

    return written[0] if written else ""


@pytest.mark.asyncio
async def test_sync_writes_anchor_entries():
    result = await _run()
    assert "bot.anchor_trigger 00000000-0000-0000-0000-000000000010" in result
    assert "bot.anchor_trigger 00000000-0000-0000-0000-000000000011" in result


@pytest.mark.asyncio
async def test_sync_uses_correct_cron_times():
    result = await _run()
    assert "0 8 * * *" in result    # 08:00
    assert "30 10 * * *" in result  # 10:30


@pytest.mark.asyncio
async def test_sync_wraps_in_markers():
    result = await _run()
    assert MARKER_START in result
    assert MARKER_END in result


@pytest.mark.asyncio
async def test_sync_preserves_existing_non_tether_entries():
    existing = "0 9 * * * /usr/bin/backup.sh\n"
    result = await _run(existing_crontab=existing)
    assert "/usr/bin/backup.sh" in result
    assert "bot.anchor_trigger" in result


@pytest.mark.asyncio
async def test_sync_replaces_old_tether_section():
    existing = f"0 9 * * * /usr/bin/backup.sh\n{MARKER_START}\n0 6 * * * old_entry\n{MARKER_END}\n"
    result = await _run(existing_crontab=existing)
    assert "old_entry" not in result
    assert "/usr/bin/backup.sh" in result
    assert "bot.anchor_trigger" in result
