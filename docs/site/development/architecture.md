# Architecture

## Repository layout

```
tether/
  api/              FastAPI application — REST endpoints, WebSocket, OAuth
  api/routes/       One file per resource group (tasks, anchors, context, events, …)
  bot/              AI agent pipeline — message handling, prompt building, anchor triggers
  config/           Baked-in config defaults (YAML) and the config loader
  db/               Database layer — Alembic migrations, PostgreSQL query functions
  frontend/         Vue 3 web dashboard (Vite, TypeScript, Pinia)
  tether_mcp/       MCP server — 9 intent-based tools exposed over SSE
  prompts/          Jinja2 prompt templates for every pipeline stage
  scripts/          Setup and maintenance scripts (configure.py, migrate_sqlite_to_postgres.py)
  tests/            pytest test suite mirroring source layout
```

## Pipeline overview

```
User message (Telegram or web chat)
  → Quick classifier (Haiku): "quick" or "full"?
  → Quick path: response builder → reply
  → Full path:
      Orchestrator (Sonnet) ↔ Meta-evaluator (Haiku)
        → Mutation planning
        → Execution subagents (Haiku, one per mutation)
        → Satisfaction eval (Haiku)
        → Response builder (Sonnet)
  → Mutations applied to PostgreSQL
  → API notified → WebSocket → Frontend updates in real time
```

The orchestrator reasons in plain English about what should happen. The meta-evaluator translates that intent into structured JSON mutations. This separation lets Sonnet focus on intent while Haiku handles structure and execution cheaply.

See [Bot Pipeline](./bot-pipeline) for a detailed walkthrough.

## Key modules

| Module | Entry point | Purpose |
|--------|-------------|---------|
| `bot/message_handler.py` | `main()` | Telegram polling loop + full pipeline orchestration |
| `bot/prompt_builder.py` | `build_anchor_prompt()` | Jinja2 prompt assembly for anchor triggers |
| `bot/handler_utils.py` | — | Slash command parsing, anchor time logic |
| `bot/anchor_trigger.py` | — | Cron-triggered anchor transition messages |
| `db/schema.py` | `init_db()` | SQLite DDL (legacy), auto-migration |
| `db/pg_queries/` | — | Async PostgreSQL query functions |
| `api/main.py` | FastAPI `app` | REST API + static file serving |
| `api/ws.py` | — | WebSocket broadcast for real-time updates |
| `tether_mcp/server.py` | FastMCP server | 9 MCP tools for context/plan management |
