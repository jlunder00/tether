"""Regression test — cron entries must source env file for DATABASE_URL + TETHER_USER_ID.

After the Postgres migration, anchor_trigger.py requires DATABASE_URL and
TETHER_USER_ID.  Cron does not inherit systemd's EnvironmentFile vars, so
the cron entry must explicitly source an env file.

The env file uses bare KEY=VALUE format (same as systemd EnvironmentFile=),
so we must use `set -a; . /file; set +a` to export vars to child processes.
"""
from __future__ import annotations

import pytest
from contextlib import asynccontextmanager
from unittest.mock import patch, AsyncMock

from bot.crontab import sync_crontab, MARKER_START, MARKER_END, _anchor_to_cron

ANCHORS = [
    {"id": "00000000-0000-0000-0000-000000000010", "name": "The Grind", "time": "08:00"},
]


async def _run_sync(existing_crontab=""):
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


# ---------------------------------------------------------------------------
# Bug B: cron entries must source env file so DATABASE_URL is available
# ---------------------------------------------------------------------------

def test_anchor_to_cron_includes_env_file_sourcing():
    """_anchor_to_cron must produce an entry that sources an env file.

    Without this, anchor_trigger.py raises KeyError: 'DATABASE_URL' because
    cron does not inherit systemd EnvironmentFile vars.
    """
    anchor = {"id": "00000000-0000-0000-0000-000000000010", "time": "08:00"}
    entry = _anchor_to_cron(anchor)

    # Entry must contain set -a to auto-export sourced vars (KEY=VALUE format)
    assert "set -a" in entry, (
        f"Cron entry must use 'set -a' to export vars from the env file.\n"
        f"Got: {entry!r}"
    )
    # Entry must source some env file
    assert ". /" in entry or ". ~" in entry or "source /" in entry, (
        f"Cron entry must source an env file ('. /path/to/env').\n"
        f"Got: {entry!r}"
    )


def test_anchor_to_cron_env_file_path_is_configurable():
    """The env file path must be configurable, not hardcoded."""
    import bot.crontab as crontab_mod

    anchor = {"id": "00000000-0000-0000-0000-000000000010", "time": "08:00"}

    with patch.object(crontab_mod, "_ENV_FILE", "/custom/path/env"):
        entry = _anchor_to_cron(anchor)

    assert "/custom/path/env" in entry, (
        f"Cron entry must use the configured env file path.\n"
        f"Got: {entry!r}"
    )


@pytest.mark.asyncio
async def test_sync_crontab_entries_source_env_file():
    """End-to-end: written crontab must include env file sourcing in each tether entry."""
    result = await _run_sync()
    lines = result.splitlines()

    tether_lines = [
        l for l in lines
        if "bot.anchor_trigger" in l
    ]
    assert tether_lines, "Expected at least one anchor_trigger line in crontab"

    for line in tether_lines:
        assert "set -a" in line, (
            f"Each anchor trigger cron line must source env with 'set -a'.\n"
            f"Got: {line!r}"
        )
