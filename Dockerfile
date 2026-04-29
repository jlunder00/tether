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
    gcc libffi-dev cron git gosu curl \
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
COPY requirements.txt pyproject.toml ./
RUN pip install --no-cache-dir --timeout 120 --retries 5 -r requirements.txt

# Application code
COPY api/ api/
COPY bot/ bot/
COPY db/ db/
COPY shared/ shared/
COPY tether_mcp/ tether_mcp/
COPY sync/ sync/
COPY integrations/ integrations/
COPY config/ config/
COPY prompts/ prompts/
COPY cron/ cron/
COPY scripts/ scripts/

# Install local package (deps already satisfied — no external downloads)
RUN pip install --no-cache-dir --no-deps .

# Frontend build artifacts
COPY --from=frontend-build /build/dist/ frontend/dist/

# ── Optional premium layer ────────────────────────────────
# Pass PREMIUM_GIT_TOKEN to install premium from the private repo.
# PREMIUM_REF is a cache-buster: change it to force a fresh install.
#   Now:    set to the premium repo HEAD SHA (7 chars)
#   Future: set to the pip version tag when a private PyPI server is ready;
#           swap the install command to: pip install tether-premium==${PREMIUM_REF}
ARG PREMIUM_GIT_TOKEN=
ARG PREMIUM_REF=unknown
RUN if [ -n "$PREMIUM_GIT_TOKEN" ]; then \
      echo "Installing tether-premium @ ${PREMIUM_REF}" && \
      pip install --no-cache-dir --timeout 120 --retries 3 \
        "git+https://${PREMIUM_GIT_TOKEN}@github.com/jlunder00/tether-premium.git" && \
      python -c "from tether_premium.register import get_premium_handler; print('[ok] premium loaded')" ; \
    else \
      echo "[skip] no token — community edition" ; \
    fi

# Default port for API
EXPOSE 8000

# Default CMD — overridden per service in docker-compose.yml
CMD ["uvicorn", "api.main:app", "--host", "0.0.0.0", "--port", "8000"]
