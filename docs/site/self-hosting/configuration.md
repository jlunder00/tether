# Configuration

Tether's configuration lives in YAML files under `~/.tether-config/`. Each file controls a specific concern. There is no monolithic config — values are organized by category and the system validates that required keys are present at startup.

## Config files

| File | What it controls | Contains secrets? |
|------|-----------------|-------------------|
| `app_config.yaml` | AI model assignments, pipeline constants, server ports, optional chat channel credentials | Yes — if Telegram configured |
| `auth_config.yaml` | JWT secret, cookie settings, CORS origins, OAuth credentials | Yes |
| `integrations.yaml` | Third-party integration flags | No |

These files are created by `make install` and updated by `make configure-*` targets. You can also edit them directly — they are standard YAML.

## LLM backends {#llm-backends}

Tether's AI agent requires access to an LLM. Several backends are supported — use whichever fits your setup:

| Backend | How to enable | Models |
|---------|--------------|--------|
| **Anthropic API** | Set `ANTHROPIC_API_KEY` env var | Claude Sonnet, Haiku, etc. |
| **Claude Code CLI** | Run `claude login` on the host | Claude models via your Anthropic subscription |
| **OpenAI-compatible** | Set `OPENAI_API_KEY` env var | GPT-4o, or any OpenAI-compatible endpoint |
| **OpenRouter** | Set `OPENROUTER_API_KEY` env var | Wide model selection via a single API key |
| **AWS Bedrock** | Configure ambient AWS credentials | Claude, Llama, and other Bedrock models |

The active backend is selected via `preferred_backend` in the LLM settings, configurable from the web dashboard under Settings → LLM. If the preferred backend is unavailable, Tether falls back automatically.

Model assignments are configured in `app_config.yaml` under `models:`.

## app_config.yaml

Controls AI model routing, pipeline behavior, and server ports.

Default baked-in values:

```yaml
models:
  orchestrator: claude-sonnet-4-6
  meta_eval: claude-haiku-4-5-20251001
  quick_classifier: claude-haiku-4-5-20251001
  response_builder: claude-sonnet-4-6
  satisfaction_eval: claude-haiku-4-5-20251001

pipeline:
  history_exchanges: 5          # conversation turns fed to the agent
  max_planning_rounds: 4        # agent ↔ interpreter iterations
  max_repair_attempts: 3        # JSON repair retries
  max_satisfaction_retries: 2   # mutation satisfaction re-checks

server:
  api_port: 8000
  mcp_port: 5001
```

## Chat channels (optional)

The AI agent can be accessed via the **web dashboard** without any additional configuration. Chat channels are optional integrations that let you reach the agent from other platforms.

### Telegram

After `make configure-telegram`, `~/.tether-config/app_config.yaml` gains:

```yaml
telegram:
  bot_token: "your-bot-token"
  chat_id: "your-chat-id"
```

Get a bot token from [@BotFather](https://t.me/BotFather) on Telegram.

```bash
make configure-telegram
```

::: info More channels coming
Discord, Slack, and email are planned as additional chat channels. The agent's web UI is available regardless of which channels are configured.
:::

## auth_config.yaml

Controls authentication and OAuth. The JWT secret is required — the app will not start without it.

```yaml
jwt:
  secret: "auto-generated-by-make-install"   # required

cookie:
  secure: true   # set false only for local HTTP dev

cors:
  allowed_origins: "http://localhost:5173,http://localhost:8000"

oauth:
  github:
    enabled: false
    client_id: ""
    client_secret: ""
    callback_url: "http://localhost:8000/auth/github/callback"
  google:
    enabled: false
    client_id: ""
    client_secret: ""
    callback_url: "http://localhost:8000/auth/google/callback"
    integration_callback_url: "http://localhost:8000/api/integrations/google/callback"
```

OAuth providers are optional — email/password login works without them. To enable GitHub or Google login:

```bash
make configure-github   # prompts for client ID, secret, callback URL
make configure-google   # prompts for client ID, secret, both callback URLs
```

::: warning Accessing Tether over HTTP
If you're accessing Tether over a plain HTTP address (not localhost), set `cookie.secure: false` in `auth_config.yaml`. HTTPS connections should always use `true`.
:::

## integrations.yaml

Controls optional third-party integrations.

```yaml
google_calendar:
  enabled: false
```

## Docker Compose env (database passwords)

Database passwords are not stored in YAML — they live in a `.env` file in the Tether repo directory (e.g. `~/tether/.env`) which Docker Compose reads at startup.

```bash
make configure-db   # prompts for POSTGRES_PASSWORD and TETHER_APP_PASSWORD
```

This writes to `~/tether/.env` (or `TETHER_COMPOSE_DIR/.env` if that env var is set).

## How resolution works

At startup, Tether loads config in layers — later layers override earlier ones:

1. **Baked-in defaults** — `config/*.yaml` in the repo (safe to commit, no secrets)
2. **Local override** — `~/.tether-config/*.yaml` (your values from `make install`)
3. **Placeholder resolution** — `${VAR:-default}` strings replaced from environment variables

You can override any value by editing `~/.tether-config/*.yaml` directly or by setting the corresponding environment variable. The `make configure-*` targets are the recommended approach for most values.

## Changing config without restarting

Config is read at startup. After editing any config file, restart the affected service:

```bash
docker compose restart api     # for auth, CORS, OAuth changes
docker compose restart bot     # for model, pipeline, channel changes
docker compose restart mcp     # for MCP-related config
```

Or restart everything:

```bash
docker compose restart
```
