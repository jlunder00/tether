#!/bin/bash
# docker-entrypoint.sh
# Downloads tether config files from a remote source before starting the app.
#
# HOW IT FITS THE CONFIG SYSTEM
# ─────────────────────────────
# config/loader.py resolves in this order (later wins):
#   1. Baked-in defaults   — config/*.yaml baked into the image
#   2. Local override      — ~/.tether-config/*.yaml  ← this script writes these
#   3. Placeholder resolve — ${VAR} / ${VAR:-default} expanded from env vars
#
# The gist holds two files that become the local override layer:
#
#   auth_config.yaml  — secrets layer: use ${VAR} for truly secret values
#                       (JWT secret, vault key, OAuth client secrets, Telegram token)
#                       use literal values for non-secret auth config
#                       (CORS origins, callback URLs, OAuth client IDs, enabled flags)
#
#   app_config.yaml   — per-env overrides: all literal values, no secrets
#                       (model assignments, feature flags, pipeline settings)
#                       omit a key to inherit the baked-in default
#
# The TetherConfig loader handles ${VAR} resolution itself — do NOT run
# envsubst on auth_config.yaml or app_config.yaml.
#
# TEMPORARY: config.yaml
# ─────────────────────
# bot/message_handler.py has its own load_config() that reads config.yaml
# raw (no placeholder resolution). Until that is updated to use TetherConfig,
# config.yaml must also be in the gist and envsubst is run on it here.
# See: https://github.com/jlunder00/tether/issues/TODO (bot-backend task)
#
# SOURCE DETECTION (URL scheme)
# ─────────────────────────────
#   https://   →  curl with optional Authorization header
#   s3://      →  aws s3 cp  (add awscli to Dockerfile apt-get if migrating)
#
# TO MIGRATE FROM GIST → S3
# ──────────────────────────
#   1. Copy *.yaml files (with ${VAR} placeholders intact) to s3://bucket/prefix/
#   2. Change CONFIG_SOURCE_URL to s3://bucket/prefix
#   3. Remove CONFIG_SOURCE_TOKEN; add AWS credentials as Fly secrets if needed
#   4. Add awscli to the Dockerfile RUN apt-get line
#   No changes to this script required.
#
# REQUIRED ENV VARS
# ─────────────────
#   CONFIG_SOURCE_URL    Base URL / S3 prefix (file names appended with /)
#                        Gist: https://gist.githubusercontent.com/USER/GIST_ID/raw
#                        S3:   s3://bucket/tether/prod
#
# OPTIONAL ENV VARS
#   CONFIG_SOURCE_TOKEN  Auth token for private sources (GitHub PAT, gist scope).
#   TETHER_CONFIG_DIR    Config directory override (default: /root/.tether-config).

set -euo pipefail

CONFIG_DIR="${TETHER_CONFIG_DIR:-/root/.tether-config}"
mkdir -p "$CONFIG_DIR"

# ── Download helpers ──────────────────────────────────────────────────────────

_fetch_to_stdout() {
    local url="$1"
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
            echo "[entrypoint] ERROR: unrecognised URL scheme: $url" >&2
            return 1
            ;;
    esac
}

_download() {
    local name="$1"
    local run_envsubst="${2:-false}"
    local url="${CONFIG_SOURCE_URL%/}/$name"
    local dest="$CONFIG_DIR/$name"

    if [ "$run_envsubst" = "true" ]; then
        # Resolve ${VAR} placeholders for callers that do raw yaml.safe_load
        # (no ${VAR:-default} support — those are left for TetherConfig).
        if _fetch_to_stdout "$url" | envsubst > "$dest"; then
            echo "[entrypoint] downloaded + resolved $name → $dest"
        else
            echo "[entrypoint] WARN: could not fetch $name" >&2
            return 1
        fi
    else
        # Leave ${VAR} / ${VAR:-default} intact — TetherConfig resolves them.
        if _fetch_to_stdout "$url" > "$dest"; then
            echo "[entrypoint] downloaded $name → $dest"
        else
            echo "[entrypoint] WARN: could not fetch $name" >&2
            return 1
        fi
    fi
}

# ── Config download ───────────────────────────────────────────────────────────

if [ -n "${CONFIG_SOURCE_URL:-}" ]; then

    # TetherConfig layer — leave placeholders for the loader to resolve.
    _download auth_config.yaml  || true
    _download app_config.yaml   || true

    # Bot backward-compat layer — bot/message_handler.py:load_config() reads
    # this file raw (no placeholder resolution), so envsubst is applied here.
    # Remove once the bot is updated to use TetherConfig.
    _download config.yaml true  || true

else
    echo "[entrypoint] WARN: CONFIG_SOURCE_URL not set — skipping remote config download" >&2
    echo "[entrypoint]       API/MCP will use baked-in defaults only." >&2
    echo "[entrypoint]       Bot will fail to start (requires telegram.bot_token)." >&2
fi

exec "$@"
