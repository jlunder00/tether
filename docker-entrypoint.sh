#!/bin/bash
# docker-entrypoint.sh
# Optionally downloads tether config override files from a remote source
# before starting the app.
#
# HOW THIS FITS THE CONFIG SYSTEM
# ────────────────────────────────
# config/loader.py (TetherConfig) resolves in order (later wins):
#   1. Baked-in defaults   — config/*.yaml baked into the image
#   2. Local override      — TETHER_CONFIG_DIR/*.yaml  ← this script writes these
#   3. Placeholder resolve — ${VAR} / ${VAR:-default} expanded from env vars
#
# The baked-in defaults + Fly secrets are sufficient to boot. The gist provides
# the LOCAL OVERRIDE layer — use it to change non-secret values (CORS origins,
# OAuth callback URLs, model assignments, feature flags) without a redeploy.
#
# WHAT TO PUT IN THE GIST
# ────────────────────────
# auth_config.yaml — literal values for non-secret auth config:
#   cors.allowed_origins, oauth.*.callback_url, oauth.*.client_id,
#   oauth.*.enabled, cookie.secure
#   (Leave jwt.secret, vault.key, client_secrets as ${VAR} — resolved from
#   Fly secrets by TetherConfig; no need to put them in the gist at all)
#
# app_config.yaml  — literal values for per-env app config:
#   model assignments, feature flags, llm settings, pipeline tuning
#   (Omit a key to inherit the baked-in default)
#
# No secrets should appear literally in either file. TetherConfig resolves
# ${VAR} placeholders from environment variables (Fly secrets) itself.
#
# SOURCE DETECTION (URL scheme)
# ─────────────────────────────
#   https://   →  curl with optional Authorization header
#   s3://      →  aws s3 cp  (add awscli to Dockerfile apt-get if migrating)
#
# TO MIGRATE FROM GIST → S3
# ──────────────────────────
#   1. Copy *.yaml files to s3://bucket/prefix/
#   2. Change CONFIG_SOURCE_URL to s3://bucket/prefix
#   3. Remove CONFIG_SOURCE_TOKEN; add AWS creds as Fly secrets if needed
#   4. Add awscli to the Dockerfile RUN apt-get line
#   No changes to this script required.
#
# ENV VARS
# ────────
#   CONFIG_SOURCE_URL    Base URL / S3 prefix (file names appended with /)
#                        Gist: https://gist.githubusercontent.com/USER/GIST_ID/raw
#                        S3:   s3://bucket/tether/prod
#                        Unset: skip download, boot from baked-in defaults + Fly secrets
#   CONFIG_SOURCE_TOKEN  Auth token for private gists (GitHub PAT, gist scope).
#   TETHER_CONFIG_DIR    Config directory (default: /root/.tether-config).

set -euo pipefail

CONFIG_DIR="${TETHER_CONFIG_DIR:-/home/tether/.tether-config}"
mkdir -p "$CONFIG_DIR"

_fetch() {
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
    local dest="$CONFIG_DIR/$name"
    local url="${CONFIG_SOURCE_URL%/}/$name"

    # TetherConfig resolves ${VAR} placeholders itself — write files as-is.
    if _fetch "$url" > "$dest"; then
        echo "[entrypoint] downloaded $name → $dest"
    else
        echo "[entrypoint] WARN: could not fetch $name — using baked-in default" >&2
        rm -f "$dest"
    fi
}

if [ -n "${CONFIG_SOURCE_URL:-}" ]; then
    _download auth_config.yaml
    _download app_config.yaml
else
    echo "[entrypoint] CONFIG_SOURCE_URL not set — booting from baked-in defaults + env vars"
fi

exec "$@"
