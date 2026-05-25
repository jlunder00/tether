# Dockerfile
# Shared image for all three Tether services (api, bot, mcp).
# The service-specific CMD is set in docker-compose.yml.

# ── Stage 1: Build Vue frontend ──────────────────────────
FROM node:20-slim AS frontend-build

WORKDIR /build
COPY frontend/package.json frontend/package-lock.json ./
RUN npm ci --ignore-scripts

COPY frontend/ ./
RUN npm run build
# Output: /build/dist/

# ── Stage 2: Python runtime ──────────────────────────────
FROM python:3.11-slim

# System deps for bcrypt, PyJWT, and potential native extensions.
# cron is needed for anchor trigger scheduling in the bot container.
# curl is needed for the NodeSource setup script.
RUN apt-get update && apt-get install -y --no-install-recommends \
    gcc libffi-dev cron git gosu curl redis-server \
    && rm -rf /var/lib/apt/lists/*

# Install Node.js 20 via NodeSource so npm has a properly self-contained
# installation (copying Node out of node:20-slim breaks npm's prefix detection).
RUN curl -fsSL https://deb.nodesource.com/setup_20.x | bash - \
    && apt-get install -y --no-install-recommends nodejs \
    && rm -rf /var/lib/apt/lists/*

# Claude Code CLI — required for `claude setup-token` in the Anthropic OAuth flow.
# Pin to a specific version for reproducible image builds.
ARG CLAUDE_CODE_VERSION=2.1.116
RUN npm install -g @anthropic-ai/claude-code@${CLAUDE_CODE_VERSION}

# Home directory template for the agent pool manager.
# Running `claude --version` once causes the CLI to write its initial config
# (~/.claude.json, ~/.claude/) into the temp home.  We snapshot that state so
# each warm subprocess gets a pre-seeded home dir, eliminating first-run setup
# time and ~/.claude.json lock contention on concurrent spawns.
# If the CLI produces no files (e.g. newer version skips auto-init), the
# template dir is left empty — the isolation benefit still applies.
RUN HOME=/tmp/claude-template \
      claude --version 2>/dev/null || true \
    && mkdir -p /etc/claude-home-template \
    && cp -r /tmp/claude-template/. /etc/claude-home-template/ 2>/dev/null || true \
    && chmod -R a+rX /etc/claude-home-template

# Non-root user for running services. UID 1000 matches the default Pi user
# so bind-mounted /data files are accessible without permission issues.
RUN useradd -m -u 1000 -s /bin/bash tether

# Runtime directory for ephemeral Anthropic credential files (vault materialize).
# Created here so the tether user owns it from the start; mode 0700 prevents
# other users from listing or reading decrypted credential files.
RUN mkdir -p /run/tether/creds \
    && chown tether:tether /run/tether/creds \
    && chmod 0700 /run/tether/creds

WORKDIR /app

# External dependencies (cached layer — only reruns when requirements.txt changes)
COPY requirements.txt pyproject.toml alembic.ini ./
RUN pip install --no-cache-dir -r requirements.txt

# Process manager for multi-service Fly.io deployments.
# supervisor is intentionally not in requirements.txt — it's infrastructure,
# not an application dependency, and shouldn't affect the dev/test environment.
RUN pip install --no-cache-dir supervisor

# Application code
COPY agent_pool_manager/ agent_pool_manager/
COPY api/ api/
COPY bot/ bot/
COPY db/ db/
COPY shared/ shared/
COPY tether_mcp/ tether_mcp/
COPY sync/ sync/
COPY integrations/ integrations/
COPY interactive_agent_layer/ interactive_agent_layer/
COPY config/ config/
COPY prompts/ prompts/
COPY cron/ cron/
COPY scripts/ scripts/
COPY alembic.ini ./

# Install local package (deps already satisfied — no external downloads)
RUN pip install --no-cache-dir --no-deps .

# supervisord config — copied late so it doesn't bust the dependency cache
COPY supervisord.conf .

# Frontend build artifacts
COPY --from=frontend-build /build/dist/ frontend/dist/

# Deployment version tag — set by CI from pyproject.toml, defaults to "dev".
# Baked in as an env var so all services can report it at runtime.
ARG TETHER_VERSION=dev
ENV TETHER_VERSION=${TETHER_VERSION}
ENV TETHER_CONFIG_DIR=/home/tether/.tether-config

# ── Optional premium layer ────────────────────────────────
# PREMIUM_GIT_TOKEN: GitHub PAT with repo access to tether-premium.
# PREMIUM_REQUIREMENTS: which requirements file to use for premium.
#   requirements-premium.txt     — prod (pinned stable, default)
#   requirements-premium-dev.txt — dev  (pinned alpha)
# To upgrade premium: bump the version pin in the relevant requirements file.
ARG PREMIUM_GIT_TOKEN=
ARG PREMIUM_REQUIREMENTS=requirements-premium.txt
COPY requirements-premium.txt requirements-premium-dev.txt ./
RUN if [ -n "$PREMIUM_GIT_TOKEN" ]; then \
      git config --global \
        url."https://${PREMIUM_GIT_TOKEN}@github.com/".insteadOf \
        "https://github.com/" \
      && pip install --no-cache-dir --timeout 120 --retries 3 \
           -r "${PREMIUM_REQUIREMENTS}" \
      && git config --global --unset \
           url."https://${PREMIUM_GIT_TOKEN}@github.com/".insteadOf \
      && python -c "from tether_premium.register import get_premium_handler; print('[ok] premium loaded')" ; \
    else \
      echo "[skip] no token — community edition" ; \
    fi

# Default port for API
EXPOSE 8000

# Entrypoint: downloads ~/.tether-config/{config,anchors}.yaml from a remote
# source (gist or S3) before handing off to the CMD.  See docker-entrypoint.sh
# for the URL scheme detection logic and S3 migration notes.
# Pi deployments override ENTRYPOINT via docker-compose so this has no effect there.
COPY docker-entrypoint.sh /usr/local/bin/docker-entrypoint.sh
RUN chmod +x /usr/local/bin/docker-entrypoint.sh
ENTRYPOINT ["/usr/local/bin/docker-entrypoint.sh"]

# Default CMD — runs all services via supervisord on Fly.io.
# Overridden per service in docker-compose.yml for Pi deployments.
CMD ["supervisord", "-c", "/app/supervisord.conf"]
