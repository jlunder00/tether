import pytest
from unittest.mock import patch, call
from pathlib import Path
from db.schema import init_db
from db.queries import upsert_anchor
from bot.crontab import sync_crontab, MARKER_START, MARKER_END


@pytest.fixture
def db_path(tmp_path):
    path = tmp_path / "tether.db"
    init_db(path)
    upsert_anchor(path, {"id": "grind_am", "name": "The Grind", "time": "08:00",
                          "duration_minutes": 120, "flexibility": "locked",
                          "strictness": 4, "color": "#e05c5c", "position": 0})
    upsert_anchor(path, {"id": "deep_work", "name": "Deep Work", "time": "10:30",
                          "duration_minutes": 120, "flexibility": "flexible",
                          "strictness": 2, "color": "#7c6af7", "position": 1})
    return path


def _run_sync(db_path, existing_crontab=""):
    """Helper: run sync_crontab with mocked subprocess, return written crontab."""
    written = []

    def fake_run(cmd, **kwargs):
        if cmd == ["crontab", "-l"]:
            class R:
                stdout = existing_crontab
                returncode = 0 if existing_crontab else 1
            return R()
        if cmd == ["crontab", "-"]:
            written.append(kwargs["input"])
            class R:
                returncode = 0
            return R()

    with patch("bot.crontab.subprocess.run", side_effect=fake_run):
        sync_crontab(db_path)

    return written[0] if written else ""


def test_sync_writes_anchor_entries(db_path):
    result = _run_sync(db_path)
    assert "bot.anchor_trigger grind_am" in result
    assert "bot.anchor_trigger deep_work" in result


def test_sync_uses_correct_cron_times(db_path):
    result = _run_sync(db_path)
    assert "0 8 * * *" in result   # 08:00
    assert "30 10 * * *" in result  # 10:30


def test_sync_wraps_in_markers(db_path):
    result = _run_sync(db_path)
    assert MARKER_START in result
    assert MARKER_END in result


def test_sync_preserves_existing_non_tether_entries(db_path):
    existing = "0 9 * * * /usr/bin/backup.sh\n"
    result = _run_sync(db_path, existing_crontab=existing)
    assert "/usr/bin/backup.sh" in result
    assert "bot.anchor_trigger grind_am" in result


def test_sync_replaces_old_tether_section(db_path):
    existing = f"0 9 * * * /usr/bin/backup.sh\n{MARKER_START}\n0 6 * * * old_entry\n{MARKER_END}\n"
    result = _run_sync(db_path, existing_crontab=existing)
    assert "old_entry" not in result
    assert "/usr/bin/backup.sh" in result
    assert "bot.anchor_trigger grind_am" in result
