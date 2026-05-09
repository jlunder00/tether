#!/bin/bash
# docker-entrypoint.sh
# Downloads tether config files from a remote source and substitutes secret
# placeholders from environment variables before starting the app.
#
# This mirrors the ~/.tether-config/ directory that the Pi setup creates:
#   config.yaml    — Telegram token, chat ID, model assignments, etc.
#   anchors.yaml   — Time block definitions for the scheduler
#
# Template substitution:
#   Config files in the gist use ${PLACEHOLDER} markers for secret values.
#   envsubst fills them in from environment variables (Fly secrets) at startup.
#   Non-secret config lives as literal values in the gist — no Fly secret needed.
#   This mirrors the Pi's configure.py / make configure pattern.
#
#   Example gist config.yaml:
#     telegram:
#       bot_token: "${TELEGRAM_BOT_TOKEN}"
#       chat_id: "${TELEGRAM_CHAT_ID}"
#     models:
#       orchestrator: claude-sonnet-4-6   ← literal, not a placeholder
#
# tether.db is not downloaded — Fly.io uses Postgres via DATABASE_URL.
# telegram_offset is ephemeral — the bot creates it on first poll.
#
# Source is detected from the URL scheme:
#   https://   →  curl with optional auth token header
#   s3://      →  aws s3 cp  (requires awscli in image; add to Dockerfile if migrating)
#
# Required env vars:
#   CONFIG_SOURCE_URL    Base URL / S3 prefix.  File names are appended with a slash.
#                        Gist example:  https://gist.githubusercontent.com/USER/ID/raw
#                        S3 example:    s3://my-bucket/tether/prod
#
# Optional env vars:
#   CONFIG_SOURCE_TOKEN  Auth token for private sources (GitHub PAT with gist scope).
#                        Not needed for public gists or S3 with IAM roles.
#   TETHER_CONFIG_DIR    Override config directory (default: /root/.tether-config).
#
# To migrate from gist → S3:
#   1. Copy config files (with placeholders intact) to s3://bucket/prefix/
#   2. Change CONFIG_SOURCE_URL to s3://bucket/prefix  (remove CONFIG_SOURCE_TOKEN)
#   3. Add AWS_ACCESS_KEY_ID + AWS_SECRET_ACCESS_KEY as Fly secrets (or use IAM)
#   4. Add awscli to the Dockerfile RUN apt-get line

set -euo pipefail

CONFIG_DIR="${TETHER_CONFIG_DIR:-/root/.tether-config}"
mkdir -p "$CONFIG_DIR"

_download_file() {
    local name="$1"
    local url="${CONFIG_SOURCE_URL%/}/$name"

    case "$url" in
        s3://*)
            aws s3 cp "$url" -
            ;;
        https://*)
            if [ -n "${CONFIG_SOURCE_TOKEN:-}" ]; then
                curl -sfL -H "Authorization: token ${CONFIG_SOURCE_TOKEN}" "$url"
            else
                curl -sfL "$url"
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
        dest="$CONFIG_DIR/$config_file"
        # Download to stdout, pipe through envsubst to fill in ${PLACEHOLDER} markers,
        # write resolved file.  Mirrors the Pi's configure.py / make configure step.
        if _download_file "$config_file" | envsubst > "$dest"; then
            echo "[entrypoint] downloaded and resolved $config_file → $dest"
        else
            echo "[entrypoint] WARN: could not fetch $config_file — app may fail to start" >&2
        fi
    done
else
    echo "[entrypoint] WARN: CONFIG_SOURCE_URL not set — skipping remote config download" >&2
fi

exec "$@"
