#!/usr/bin/env bash
set -euo pipefail

CONFIG_DIR="${TETHER_CONFIG_DIR:-$HOME/.tether-config}"
BACKUP_DIR="$CONFIG_DIR/backups/$(date +%Y%m%d_%H%M%S)"
mkdir -p "$BACKUP_DIR"

cp "$CONFIG_DIR/auth.db" "$BACKUP_DIR/auth.db"
cp -r "$CONFIG_DIR/users/" "$BACKUP_DIR/users/"

echo "Backup created at: $BACKUP_DIR"
ls -lR "$BACKUP_DIR"
