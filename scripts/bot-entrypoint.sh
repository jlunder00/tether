#!/usr/bin/env bash
set -euo pipefail

# Start cron daemon in background (needed for anchor triggers).
# bot/crontab.py writes cron entries for anchor transition scheduling.
cron

echo "[bot-entrypoint] cron started, launching bot..."

# Run the bot (exec replaces shell so signals propagate correctly)
exec python -m bot.message_handler "$@"
