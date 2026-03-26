#!/usr/bin/env bash
# Sync personal config from laptop to Pi.
# plan.yaml is NOT synced — it lives on the Pi.

set -euo pipefail

PI_HOST="${TETHER_PI_HOST:-toast@10.0.0.199}"
REMOTE_DIR="~/.tether-config/"
LOCAL_DIR="$HOME/.tether-config/"

echo "[tether] Syncing config to $PI_HOST..."
rsync -avz --exclude "plan.yaml" "$LOCAL_DIR" "$PI_HOST:$REMOTE_DIR"
echo "[tether] Done."
