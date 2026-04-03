# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## What This Is

Tether is a Telegram-based daily task management bot with LLM integration. It runs on a Raspberry Pi on a Tailnet, uses Claude Code CLI (`claude -p`) for reasoning, and exposes an MCP server for external tool access. A Vue 3 dashboard provides a web UI.

## Commands

```bash
# Install (editable, with dev deps)
pip install -e ".[dev]"

# Run the bot (Telegram polling)
python -m bot.message_handler

# Run the API server
uvicorn api.main:app --host 0.0.0.0 --port 8000

# Run the MCP server (SSE on port 5001)
python -m tether_mcp.server --sse

# Run tests
pytest -v

# Run a single test file
pytest tests/bot/test_handler_utils.py -v

# Frontend (from frontend/)
cd frontend && npm install && npm run dev   # dev
cd frontend && npm run build                # production
```

## Architecture

### Pipeline Flow

User messages arrive via Telegram long-polling and are routed through a multi-stage reasoning pipeline:

```
Telegram message
  → Quick classifier (Haiku): "quick" or "full"?
  → Quick path: response_builder → reply
  → Full path: Orchestrator loop (Sonnet) ↔ Meta-eval (Haiku)
      → Mutation planning → Subagent execution (Haiku)
      → Satisfaction eval → Response builder (Sonnet)
  → Mutations applied to SQLite
  → Response sent via Telegram
  → API notified → WebSocket → Frontend updates
```

The orchestrator reasons in plain English; the meta-evaluator translates intent into structured JSON mutations. This separation lets Sonnet focus on intent while Haiku handles structure/execution cheaply.

### Key Modules

| Module | Entry Point | Purpose |
|--------|-------------|---------|
| `bot/message_handler.py` | `main()` | Telegram polling loop, full pipeline orchestration |
| `bot/prompt_builder.py` | `build_anchor_prompt()` | Jinja2 prompt assembly for anchor triggers |
| `bot/handler_utils.py` | — | Slash command parsing, anchor time logic |
| `bot/anchor_trigger.py` | — | Cron-triggered anchor transition messages |
| `bot/crontab.py` | `sync_crontab()` | Syncs anchor schedule to system crontab |
| `db/schema.py` | `init_db()` | SQLite DDL, auto-migration |
| `db/queries.py` | — | All DB read/write operations |
| `api/main.py` | FastAPI `app` | REST API + static file serving |
| `api/ws.py` | — | WebSocket broadcast for real-time updates |
| `api/routes/` | — | CRUD endpoints (anchors, tasks, context, plan, milestones, logs) |
| `tether_mcp/server.py` | FastMCP server | MCP tools for context/plan management |

### Prompt Templates

All prompts live in `prompts/*.md` as Jinja2 markdown templates. Key templates:

- `orchestrator.md` — Multi-round reasoning (receives plan, context subjects, history, user message)
- `meta_eval.md` — Interprets orchestrator output → JSON (context_to_fetch, mutation_plan, orchestrator_done)
- `response_builder.md` — Assembles final user-facing message from subagent reports
- `quick_classifier.md` — Routes messages to quick or full pipeline
- `satisfaction_eval.md` — Binary check: did mutations succeed?
- `subagent_patch.md` / `subagent_upsert.md` — Mutation execution prompts

### LLM Invocation

Claude is invoked via subprocess:
```python
subprocess.run(["claude", "-p", "--strict-mcp-config", "--model", model, prompt], ...)
```

Model roles are configured in `~/.tether-config/config.yaml` under `models:` with fallback defaults in `message_handler.py:_MODEL_DEFAULTS`.

### Database

SQLite at `~/.tether-config/tether.db`. Key tables: `anchors`, `plans`, `tasks`, `task_dependencies`, `context_entries`, `milestones`, `milestone_tasks`, `conversation_history`, `orchestrator_conversation`, `staging_mutations`, `invocation_log`, `followup_state`, `acknowledgements`, `check_ins`.

### MCP Server Tools

Exposed via SSE on port 5001: `list_context_entries`, `get_context_entry`, `update_context_entry`, `append_context_entry`, `patch_context_entry`, `get_today_plan`, `update_plan_tasks`, `get_anchors`, `get_current_anchor`, `get_bot_log`, `get_milestones`.

## Configuration

- `~/.tether-config/config.yaml` — Telegram bot token, chat ID, schedule, model assignments, followup config
- `~/.tether-config/anchors.yaml` — Anchor definitions (time blocks with flexibility/strictness)
- `TETHER_DB_PATH` env var overrides default DB location

## Deployment

Three systemd services on the Pi: `tether-bot`, `tether-api`, `tether-mcp`. GitHub Actions (`deploy.yml`) auto-deploys on push to `main` via self-hosted runner.

## Pipeline Constants

```python
HISTORY_EXCHANGES = 5          # conversation turns fed to orchestrator
MAX_PLANNING_ROUNDS = 4        # orchestrator ↔ meta-eval iterations
MAX_REPAIR_ATTEMPTS = 3        # meta-eval JSON repair retries
MAX_SATISFACTION_RETRIES = 2   # mutation satisfaction re-checks
```

## Conventions

- Python 3.11+, no type stubs required but type hints preferred
- Tests in `tests/` mirroring source layout, pytest with asyncio_mode=auto
- Jinja2 templates: `trim_blocks=True`, `lstrip_blocks=True`
- The bot is single-threaded; module-level mutable state is safe
- Prompt changes are high-impact — test with real Telegram messages before merging
