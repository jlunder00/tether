"""Regression guard for the Neon-idle-spin-down gating fix (shared/notify_due.py).

The Redis next-due gate (see PR #468) only works when the process actually
has a Redis client to talk to. Every supervisord program whose command
invokes code that imports shared.notify_due MUST have REDIS_URL set in its
``environment=`` line — otherwise ``notify_due.is_due()``/``get_due_user_ids()``
silently fail open (no REDIS_URL => no client => "treat as due"), and the
gating becomes a permanent no-op: the exact bug this test guards against
(the bot process was shipped without REDIS_URL, making the whole fix inert
in that process while looking correct in code review and tests).

This is deliberately a config-parsing test, not a live-Redis test — it
would have caught the missing REDIS_URL on `[program:bot]` at review time
without needing a running supervisord/Redis instance.
"""
from __future__ import annotations

import configparser
from pathlib import Path

REPO_ROOT = Path(__file__).parent.parent.parent
SUPERVISORD_CONF = REPO_ROOT / "supervisord.conf"

# Programs whose command invokes code that imports shared.notify_due today:
#   - api   (uvicorn api.main:app)      -> api/routes/internal.py, api/routes/anchors.py
#   - bot   (python -m bot.message_handler) -> bot/message_handler.py
# If a new program starts calling shared.notify_due, add it here (and to
# supervisord.conf) in the same change.
PROGRAMS_REQUIRING_REDIS_URL = {"api", "bot"}


def _load_supervisord_conf() -> configparser.ConfigParser:
    cp = configparser.ConfigParser(strict=False)
    cp.read(SUPERVISORD_CONF)
    return cp


def _environment_dict(cp: configparser.ConfigParser, section: str) -> dict[str, str]:
    """Parse a supervisord `environment=KEY="val",KEY2="val2"` line into a dict."""
    raw = cp[section].get("environment", "")
    env: dict[str, str] = {}
    for pair in raw.split(","):
        pair = pair.strip()
        if not pair or "=" not in pair:
            continue
        key, _, value = pair.partition("=")
        env[key.strip()] = value.strip().strip('"')
    return env


def test_supervisord_conf_exists():
    assert SUPERVISORD_CONF.is_file(), f"expected {SUPERVISORD_CONF} to exist"


def test_every_notify_due_caller_program_has_redis_url():
    cp = _load_supervisord_conf()

    for program in PROGRAMS_REQUIRING_REDIS_URL:
        section = f"program:{program}"
        assert section in cp.sections(), (
            f"expected a [{section}] section in supervisord.conf"
        )
        env = _environment_dict(cp, section)
        assert "REDIS_URL" in env, (
            f"[{section}] is missing REDIS_URL — shared.notify_due gating "
            f"will silently fail open (always 'due') in this process, "
            f"defeating the Neon idle-spin-down fix. See module docstring "
            f"in shared/notify_due.py and PR #468."
        )
        assert env["REDIS_URL"], f"[{section}] has an empty REDIS_URL value"


def test_bot_and_api_redis_url_match_the_supervisord_local_redis():
    """Both notify_due-calling programs must point at the SAME Redis instance
    (the local supervisord-managed redis-server) so they share one due_queue —
    if they pointed at different instances, gating would be inconsistent
    between the cron path and the polling-loop path."""
    cp = _load_supervisord_conf()
    api_env = _environment_dict(cp, "program:api")
    bot_env = _environment_dict(cp, "program:bot")

    assert api_env["REDIS_URL"] == bot_env["REDIS_URL"]
