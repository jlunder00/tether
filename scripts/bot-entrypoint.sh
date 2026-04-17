#!/usr/bin/env bash
set -euo pipefail

# Start cron daemon as root (needed for anchor trigger scheduling).
cron

echo "[bot-entrypoint] cron started, launching bot..."

# Silence the Claude CLI "configuration file not found" warning.
# The CLI probes ~/.claude.json as a settings file (sibling of the ~/.claude
# credentials dir). We don't have settings to configure, but an empty stub
# keeps the CLI quiet across subprocess_cli probes.
CLAUDE_JSON="/home/tether/.claude.json"
if [ ! -f "$CLAUDE_JSON" ]; then
  echo '{}' > "$CLAUDE_JSON"
  chown tether:tether "$CLAUDE_JSON" 2>/dev/null || true
fi

# Drop to non-root user before launching the bot.
# Claude SDK refuses --dangerously-skip-permissions when running as root.
exec gosu tether python -m bot.message_handler "$@"
