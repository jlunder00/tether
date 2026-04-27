# Tether build & deployment helpers
#
# Variables (all overridable):
#   PREMIUM_GIT_TOKEN  GitHub PAT for cloning tether-premium (required for premium builds)
#   PREMIUM_REF        Cache-buster: SHA (now) or version tag (when private PyPI is ready).
#                      Auto-fetched from remote HEAD if unset and TOKEN is set.
#   IMAGE              Docker image name  (default: tether-premium)
#   TAG                Image tag          (default: dev)
#
# Swapping to private PyPI (future):
#   Replace the PREMIUM_REF auto-fetch below with:
#     PREMIUM_REF ?= $(shell pip index versions tether-premium 2>/dev/null | awk '{print $$NF}')
#   And update the Dockerfile install command from git+https://... to
#     pip install tether-premium==$(PREMIUM_REF)

IMAGE             ?= tether-premium
TAG               ?= dev
PREMIUM_GIT_TOKEN ?=
# Resolve PREMIUM_REF: caller can pass it explicitly; otherwise fetch remote HEAD SHA.
PREMIUM_REF       ?= $(shell \
  [ -n "$(PREMIUM_GIT_TOKEN)" ] && \
  git ls-remote "https://$(PREMIUM_GIT_TOKEN)@github.com/jlunder00/tether-premium.git" HEAD \
    2>/dev/null | cut -f1 | cut -c1-7 || echo unknown)

COMPOSE_ENV = PREMIUM_GIT_TOKEN=$(PREMIUM_GIT_TOKEN) \
              PREMIUM_REF=$(PREMIUM_REF) \
              IMAGE_TAG=$(TAG) \
              TETHER_IMAGE=$(IMAGE)

.PHONY: build build-premium build-community \
        build-no-cache build-premium-no-cache build-community-no-cache \
        up down restart \
        deploy deploy-no-cache deploy-community \
        tag-latest \
        install \
        configure-auth configure-google configure-github configure-db configure-telegram \
        generate-bot-token

# ── Build targets ─────────────────────────────────────────

build: build-premium

build-premium:
	$(COMPOSE_ENV) docker compose build

build-community:
	IMAGE_TAG=$(TAG) TETHER_IMAGE=ghcr.io/jlunder00/tether docker compose build

build-no-cache: build-premium-no-cache

build-premium-no-cache:
	$(COMPOSE_ENV) docker compose build --no-cache

build-community-no-cache:
	IMAGE_TAG=$(TAG) TETHER_IMAGE=ghcr.io/jlunder00/tether docker compose build --no-cache

# ── Service targets ───────────────────────────────────────

up:
	TETHER_IMAGE=$(IMAGE) IMAGE_TAG=$(TAG) docker compose up -d

down:
	TETHER_IMAGE=$(IMAGE) docker compose down || true

restart: down up

# ── Combined deploy targets ───────────────────────────────

deploy: build up

deploy-no-cache: build-premium-no-cache up

deploy-community: build-community
	IMAGE_TAG=$(TAG) TETHER_IMAGE=ghcr.io/jlunder00/tether docker compose up -d

# ── Tagging ───────────────────────────────────────────────

tag-latest:
	docker tag $(IMAGE):$(TAG) $(IMAGE):latest

# ── Configuration targets ─────────────────────────────────
#
# Run interactively (self-hoster): make install
# Run from CI/GHA (pass values as make args): make configure-auth TETHER_JWT_SECRET=...
#
# Env overrides:
#   TETHER_CONFIG_DIR    Where YAML config files are written (default: ~/.tether-config)
#   TETHER_COMPOSE_DIR   Where the Docker Compose .env is written (default: ~/tether)

install:
	python3 scripts/configure.py install

configure-auth:
	python3 scripts/configure.py auth \
	    TETHER_JWT_SECRET="$(TETHER_JWT_SECRET)" \
	    TETHER_COOKIE_SECURE="$(TETHER_COOKIE_SECURE)" \
	    TETHER_ALLOWED_ORIGINS="$(TETHER_ALLOWED_ORIGINS)"

configure-google:
	python3 scripts/configure.py google \
	    GOOGLE_CLIENT_ID="$(GOOGLE_CLIENT_ID)" \
	    GOOGLE_CLIENT_SECRET="$(GOOGLE_CLIENT_SECRET)" \
	    GOOGLE_CALLBACK_URL="$(GOOGLE_CALLBACK_URL)" \
	    GOOGLE_INTEGRATION_CALLBACK_URL="$(GOOGLE_INTEGRATION_CALLBACK_URL)"

configure-github:
	python3 scripts/configure.py github \
	    GITHUB_CLIENT_ID="$(GITHUB_CLIENT_ID)" \
	    GITHUB_CLIENT_SECRET="$(GITHUB_CLIENT_SECRET)" \
	    GITHUB_CALLBACK_URL="$(GITHUB_CALLBACK_URL)"

configure-db:
	python3 scripts/configure.py db \
	    POSTGRES_PASSWORD="$(POSTGRES_PASSWORD)" \
	    TETHER_APP_PASSWORD="$(TETHER_APP_PASSWORD)"
	@if [ -n "$(TETHER_APP_PASSWORD)" ]; then \
	    docker compose exec -T postgres psql -U tether \
	        -c "ALTER ROLE tether_app PASSWORD '$(TETHER_APP_PASSWORD)';" 2>/dev/null || true; \
	fi
	@if [ -n "$(POSTGRES_PASSWORD)" ]; then \
	    docker compose exec -T postgres psql -U tether \
	        -c "ALTER ROLE tether PASSWORD '$(POSTGRES_PASSWORD)';" 2>/dev/null || true; \
	fi

configure-telegram:
	python3 scripts/configure.py telegram \
	    TELEGRAM_BOT_TOKEN="$(TELEGRAM_BOT_TOKEN)" \
	    TELEGRAM_CHAT_ID="$(TELEGRAM_CHAT_ID)"

generate-bot-token:
	python3 scripts/generate_bot_token.py
