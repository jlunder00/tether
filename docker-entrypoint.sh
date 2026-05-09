#!/bin/bash
# docker-entrypoint.sh
# Downloads tether config files from a remote source before starting the app.
#
# This mirrors the ~/.tether-config/ directory that the Pi setup creates:
#   config.yaml    — Telegram token, chat ID, model assignments, etc.
#   anchors.yaml   — Time block definitions for the scheduler
#
# tether.db is not downloaded — Fly.io uses Postgres via DATABASE_URL.
# telegram_offset is ephemeral — the bot creates it on first poll.
#
# Source is detected from the URL scheme:
#   https://   →  curl with optional Bearer/token auth header
#   s3://      →  aws s3 cp  (requires awscli in image; add to Dockerfile if migrating)
#
# Required env vars:
#   CONFIG_SOURCE_URL    Base URL / S3 prefix.  File names are appended with a slash.
#                        Gist example:  https://gist.githubusercontent.com/USER/ID/raw
#                        S3 example:    s3://my-bucket/tether/prod
#
# Optional env vars:
#   CONFIG_SOURCE_TOKEN  Auth token.  For GitHub gists: a classic PAT with gist scope.
#                        Not needed for S3 (use IAM role or AWS_ACCESS_KEY_ID instead).
#   TETHER_CONFIG_DIR    Override config directory (default: /root/.tether-config).
#
# To migrate from gist → S3:
#   1. Copy config files to s3://bucket/prefix/
#   2. Change CONFIG_SOURCE_URL to s3://bucket/prefix  (remove CONFIG_SOURCE_TOKEN)
#   3. Add AWS_ACCESS_KEY_ID + AWS_SECRET_ACCESS_KEY as Fly secrets (or use IAM)
#   4. Add awscli to the Dockerfile RUN apt-get line

set -euo pipefail

CONFIG_DIR="${TETHER_CONFIG_DIR:-/root/.tether-config}"
mkdir -p "$CONFIG_DIR"

_download_file() {
    local name="$1"
    local dest="$CONFIG_DIR/$name"
    local url="${CONFIG_SOURCE_URL%/}/$name"

    case "$url" in
        s3://*)
            aws s3 cp "$url" "$dest"
            ;;
        https://*)
            if [ -n "${CONFIG_SOURCE_TOKEN:-}" ]; then
                curl -sfL -H "Authorization: token ${CONFIG_SOURCE_TOKEN}" \
                    "$url" -o "$dest"
            else
                curl -sfL "$url" -o "$dest"
            fi
            ;;
        *)
            echo "[entrypoint] ERROR: unrecognised URL scheme in CONFIG_SOURCE_URL: $url" >&2
            return 1
            ;;
    esac
}

if [ -n "${CONFIG_SOURCE_URL:-}" ]; then
    for config_file in config.yaml anchors.yaml; do
        if _download_file "$config_file"; then
            echo "[entrypoint] downloaded $config_file → $CONFIG_DIR/$config_file"
        else
            echo "[entrypoint] WARN: could not download $config_file — app may fail to start" >&2
        fi
    done
else
    echo "[entrypoint] WARN: CONFIG_SOURCE_URL not set — skipping remote config download" >&2
fi

exec "$@"
