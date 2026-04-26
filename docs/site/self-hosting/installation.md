# Installation

## Prerequisites

- **Linux** — Raspberry Pi 4+ or any x86-64 machine
- **Docker and Docker Compose** — [install Docker](https://docs.docker.com/get-docker/)
- **Python 3.11+** — for running the configure script
- **Claude Code** — install and log in: `npm install -g @anthropic-ai/claude-code && claude login`
- **A Telegram bot token** — create one via [@BotFather](https://t.me/BotFather) on Telegram

## 1. Clone the repo

```bash
git clone https://github.com/jlunder00/tether.git
cd tether
```

## 2. Run the setup script

`make install` walks you through configuration interactively. It auto-generates a secure JWT secret and prompts for each credential category. Press Enter to skip anything you don't have yet.

```bash
make install
```

You'll be prompted for:

| Category | What it sets |
|----------|-------------|
| Google OAuth | Client ID, secret, callback URLs (skip if not using Google login) |
| GitHub OAuth | Client ID, secret, callback URL (skip if not using GitHub login) |
| DB passwords | PostgreSQL superuser + app role passwords |
| Telegram | Bot token and chat ID |

Config is written to `~/.tether-config/` as YAML files. The JWT secret is generated automatically — you don't need to supply one.

## 3. Create the database app role

Tether uses a non-superuser PostgreSQL role (`tether_app`) for all application queries. This is required for per-user data isolation to work correctly. Create it once after the database container first starts:

```bash
# Start just the database
docker compose up -d postgres

# Connect and create the role
docker exec -it tether-postgres psql -U tether -d tether
```

```sql
CREATE ROLE tether_app WITH LOGIN PASSWORD 'your-tether-app-password';
GRANT CONNECT ON DATABASE tether TO tether_app;
GRANT USAGE ON SCHEMA public TO tether_app;
GRANT SELECT, INSERT, UPDATE, DELETE ON ALL TABLES IN SCHEMA public TO tether_app;
GRANT USAGE, SELECT ON ALL SEQUENCES IN SCHEMA public TO tether_app;
ALTER DEFAULT PRIVILEGES IN SCHEMA public
    GRANT SELECT, INSERT, UPDATE, DELETE ON TABLES TO tether_app;
ALTER DEFAULT PRIVILEGES IN SCHEMA public
    GRANT USAGE, SELECT ON SEQUENCES TO tether_app;
```

Use the same password you entered during `make install` when prompted for `tether_app role password`.

## 4. Run database migrations

```bash
docker compose run --rm api alembic upgrade head
```

## 5. Start all services

```bash
docker compose up -d
```

This starts four containers: `postgres`, `api`, `bot`, and `mcp`.

## 6. Verify

```bash
docker compose ps
```

All four services should show as running. Send your Telegram bot a message — it should respond. Open `http://localhost:8000` in a browser to access the web dashboard.

## Updating config after setup

Run any `configure-*` target to update a specific category without re-running the full install:

```bash
make configure-telegram   # update Telegram credentials
make configure-auth       # update JWT secret or CORS origins
make configure-google     # update Google OAuth credentials
make configure-github     # update GitHub OAuth credentials
make configure-db         # update database passwords
```

See [Configuration](./configuration) for the full config reference.
