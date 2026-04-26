# Secrets Reference

Complete reference for every secret and configuration value Tether uses. For each entry: where it lives, how to set it, and what breaks if it's missing or wrong.

## Auth config (`~/.tether-config/auth_config.yaml`)

Set via `make configure-auth` or edit the file directly.

| Key | Required | Default | What breaks if missing/wrong |
|-----|----------|---------|------------------------------|
| `jwt.secret` | **Yes** | none — app fails to start | App won't start. All login sessions are invalid. |
| `cookie.secure` | No | `true` | If `true` over HTTP: login cookies won't be sent by the browser, login fails. Set `false` for local HTTP access. |
| `cors.allowed_origins` | No | `http://localhost:5173,http://localhost:8000` | Browser requests from unlisted origins are blocked with a CORS error. |

### GitHub OAuth (`auth_config.yaml → oauth.github`)

Set via `make configure-github`. Leave `enabled: false` to disable GitHub login entirely.

| Key | Required for GitHub login | What it does |
|-----|--------------------------|-------------|
| `oauth.github.enabled` | — | Set `true` to enable the GitHub login button |
| `oauth.github.client_id` | Yes | Identifies your GitHub OAuth app |
| `oauth.github.client_secret` | Yes | Authenticates your GitHub OAuth app — keep this secret |
| `oauth.github.callback_url` | Yes | Must match the callback URL registered in your GitHub OAuth app settings |

### Google OAuth (`auth_config.yaml → oauth.google`)

Set via `make configure-google`. Leave `enabled: false` to disable Google login entirely.

| Key | Required for Google login | What it does |
|-----|--------------------------|-------------|
| `oauth.google.enabled` | — | Set `true` to enable the Google login button |
| `oauth.google.client_id` | Yes | Identifies your Google OAuth app |
| `oauth.google.client_secret` | Yes | Authenticates your Google OAuth app — keep this secret |
| `oauth.google.callback_url` | Yes | Auth callback — must match Google Cloud Console OAuth configuration |
| `oauth.google.integration_callback_url` | Yes (for Google Calendar) | Google Calendar OAuth callback — must match Google Cloud Console |

---

## App config (`~/.tether-config/app_config.yaml`)

Set via `make configure-telegram` for Telegram credentials; edit the file directly for model/pipeline tuning.

| Key | Required | Default | Notes |
|-----|----------|---------|-------|
| `telegram.bot_token` | **Yes** | none | Bot won't start without this. Get from [@BotFather](https://t.me/BotFather). |
| `telegram.chat_id` | **Yes** | none | The Telegram user or group chat ID the bot responds to. |
| `models.*` | No | See [Configuration](./configuration) | Model routing for each pipeline stage. Change if you want to use different Claude model versions. |
| `pipeline.*` | No | See [Configuration](./configuration) | Planning loop constants. Rarely need changing. |
| `server.api_port` | No | `8000` | REST API port |
| `server.mcp_port` | No | `5001` | MCP server SSE port |

---

## Database passwords (`~/tether/.env`)

Set via `make configure-db`. Written to the Docker Compose `.env` file, not a YAML config.

| Variable | Required | Default (insecure) | What breaks if wrong |
|----------|----------|--------------------|----------------------|
| `POSTGRES_PASSWORD` | **Yes** | `tether_dev` | Database won't initialize correctly. Change before any multi-user or network-accessible deployment. |
| `TETHER_APP_PASSWORD` | **Yes** | `tether_app_dev` | App can't connect to the database. Must match the password used when creating the `tether_app` role. |

::: danger Change these defaults
The default passwords (`tether_dev`, `tether_app_dev`) are public knowledge. Anyone who can reach your database port can connect with them. Always set strong passwords before exposing Tether to a network.
:::

---

## Environment variables (advanced)

These control where Tether looks for config and compose files. Rarely need changing.

| Variable | Default | What it does |
|----------|---------|-------------|
| `TETHER_CONFIG_DIR` | `~/.tether-config` | Where `app_config.yaml`, `auth_config.yaml`, etc. are read from |
| `TETHER_COMPOSE_DIR` | `~/tether` | Where the Docker Compose `.env` is written by `make configure-db` |
| `TETHER_USER_ID` | _(empty)_ | Scopes MCP queries to a specific user. Required if using MCP with multiple users. |

---

## What `make install` sets automatically

| Value | How it's set |
|-------|-------------|
| `jwt.secret` | Auto-generated via `secrets.token_hex(32)` — cryptographically random, 64 hex chars |
| Everything else | Prompted interactively — press Enter to skip and set later with `make configure-*` |
