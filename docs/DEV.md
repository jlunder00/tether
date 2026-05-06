# Dev Deployment (Pi)

The `dev` branch deploys a parallel stack on the same Pi as production, used for
regression testing and validating PRs before they merge to `main`.

## Architecture

| Component        | Production              | Dev                            |
|------------------|-------------------------|--------------------------------|
| Code directory   | `/home/toast/tether`    | `/home/toast/tether-dev`       |
| Config directory | `~/.tether-config`      | `~/.tether-config-dev`         |
| Docker project   | `tether` (default)      | `tether-dev`                   |
| Docker image     | `tether-premium`        | `tether-premium-dev`           |
| Compose files    | `docker-compose.yml`    | `+docker-compose.dev.yml`      |
| API port         | `8000`                  | `8001`                         |
| MCP port         | `5001`                  | `5002`                         |
| Postgres port    | `5432` (host-exposed)   | internal only (no host binding)|
| Bot              | `tether-bot-staging` → | separate docker service        |

## GitHub Actions Workflows

| Workflow                        | Trigger               | What it does                          |
|---------------------------------|-----------------------|---------------------------------------|
| `pi-deploy-dev-api.yml`         | push to `dev` (api/*) | Build & restart dev API on port 8001  |
| `pi-deploy-dev-bot.yml`         | push to `dev` (bot/*) | Build & restart dev bot               |
| `pi-force-deploy-all.yml`       | `workflow_dispatch`   | Add `target=dev` to force full redeploy |

All workflows (production + dev) share the `pi-deploy` concurrency group so only one
deploy runs at a time on the shared self-hosted runner.

## tether-premium Integration

When `dev` is pushed in `tether-premium`, the `trigger-deploy-dev.yml` workflow
dispatches `pi-deploy-dev-bot.yml` in this repo via `workflow_dispatch`. This keeps
the dev bot in sync with premium changes on the `dev` branch.

## Required GitHub Secrets

The following secrets must be added to the **tether** repo settings before dev deploys
will work. Most share the same OAuth app as production — only callback URLs differ.

| Secret                               | Description                                    |
|--------------------------------------|------------------------------------------------|
| `TETHER_ALLOWED_ORIGINS_DEV`         | Allowed CORS origins for dev API               |
| `GOOGLE_CALLBACK_URL_DEV`            | OAuth callback pointing to dev (port 8001)     |
| `GOOGLE_INTEGRATION_CALLBACK_URL_DEV`| Google integration callback for dev            |
| `GH_CALLBACK_URL_DEV`                | GitHub OAuth callback for dev                  |
| `TETHER_VAULT_KEY_DEV`               | Vault key for dev config encryption            |
| `TELEGRAM_BOT_TOKEN_DEV`             | Telegram bot token for the dev bot             |
| `TELEGRAM_CHAT_ID_DEV`               | Telegram chat ID for the dev bot               |

## One-time Pi Setup

On first deploy, the CI workflow auto-clones the dev repo:
```bash
git clone git@github.com:jlunder00/tether.git /home/toast/tether-dev --branch dev
```

After that, every push to `dev` does `git pull origin dev` to update.

The `~/.tether-config-dev` directory is created automatically by `scripts/configure.py`
on first config write.

## Exposing Dev Externally (Tailscale Funnel)

To make the dev API reachable outside the local network, run once manually on the Pi:

```bash
tailscale funnel --bg 8001
```

This is intentionally not automated in CI — it's a one-time Pi setup step.

For the dev frontend (if needed), configure a separate nginx vhost:
```nginx
server {
    listen 443 ssl;
    server_name dev.your-tailscale-domain.ts.net;
    location / {
        proxy_pass http://localhost:8001;
    }
}
```

## Note on systemd Service Files

The `systemd/` directory contains bare-metal service files (`tether-api.service`, etc.)
that run uvicorn directly from a virtualenv. These are **production-only** and not used
by the dev pipeline. The CI deploy path (both production and dev) uses `docker compose`.
