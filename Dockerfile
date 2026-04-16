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
RUN apt-get update && apt-get install -y --no-install-recommends \
    gcc libffi-dev cron \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app

# Python dependencies (cached layer — changes less often than code)
COPY pyproject.toml ./
RUN pip install --no-cache-dir -e . 2>/dev/null || pip install --no-cache-dir .

# Application code
COPY api/ api/
COPY bot/ bot/
COPY db/ db/
COPY tether_mcp/ tether_mcp/
COPY config/ config/
COPY prompts/ prompts/
COPY cron/ cron/
COPY scripts/ scripts/

# Frontend build artifacts
COPY --from=frontend-build /build/dist/ frontend/dist/

# ── Optional premium layer ────────────────────────────────
# Pass --build-arg GITHUB_TOKEN=<token> to install premium from the private
# repo. If omitted or empty, this produces the community edition image.
ARG GITHUB_TOKEN=
RUN if [ -n "$GITHUB_TOKEN" ]; then \
      pip install --no-cache-dir \
        "git+https://${GITHUB_TOKEN}@github.com/jlunder00/tether-premium.git" && \
      python -c "from tether_premium.register import get_premium_handler; print('[ok] premium loaded')" ; \
    else \
      echo "[skip] no GITHUB_TOKEN — community edition" ; \
    fi

# Default port for API
EXPOSE 8000

# Default CMD — overridden per service in docker-compose.yml
CMD ["uvicorn", "api.main:app", "--host", "0.0.0.0", "--port", "8000"]
