#!/usr/bin/env bash
set -euo pipefail

# Start cron daemon as root (needed for anchor trigger scheduling).
cron

echo "[bot-entrypoint] cron started, launching bot..."

# Drop to non-root user before launching the bot.
# Claude SDK refuses --dangerously-skip-permissions when running as root.
exec gosu tether python -m bot.message_handler "$@"
