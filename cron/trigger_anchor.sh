#!/usr/bin/env bash
# Invoked by crontab: trigger_anchor.sh <anchor_id>
# Example: 0 8 * * * /home/toast/tether/cron/trigger_anchor.sh grind_am

set -euo pipefail

ANCHOR_ID="${1:?Usage: trigger_anchor.sh <anchor_id>}"
REPO_DIR="$(cd "$(dirname "$0")/.." && pwd)"
VENV_DIR="$REPO_DIR/.venv"

source "$VENV_DIR/bin/activate"
cd "$REPO_DIR"
python -m bot.anchor_trigger "$ANCHOR_ID"
