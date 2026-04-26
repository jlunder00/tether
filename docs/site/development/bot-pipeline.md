# Bot Pipeline

This page explains how a user message flows through Tether's AI pipeline from arrival to response.

## Stages

### 1 — Quick classifier

Every incoming message first hits a fast classifier (Haiku model). It decides whether the message needs the full reasoning pipeline or can be answered quickly.

- **Quick path:** Simple queries, confirmations, and greetings go directly to the response builder.
- **Full path:** Planning requests, task mutations, and anything requiring context fetch go through the orchestrator loop.

### 2 — Orchestrator loop (full path only)

The orchestrator (Sonnet) reasons in plain English about what the user wants. It receives:

- Today's date and current time block (anchor)
- Today's plan (human-readable)
- Available context topics (names only)
- Recent conversation history
- A summary from the previous meta-evaluator round (if any)
- Any context fetched in the previous round

The orchestrator **does not** see mutation syntax, anchor IDs, or database schema. It simply writes what it thinks should happen in natural language.

### 3 — Meta-evaluator

Runs after every orchestrator response. It reads the full orchestrator conversation and translates intent into a structured JSON plan:

```json
{
  "summary": "Plain-English explanation for the orchestrator",
  "context_to_fetch": [...],
  "mutation_plan": [...],
  "orchestrator_done": false
}
```

The `summary` is injected back into the orchestrator's next round so it knows what was decided. If `context_to_fetch` is non-empty, the meta-evaluator retrieves those items and they appear in the next orchestrator round. The loop continues until `orchestrator_done` is true or the round limit is reached.

**Model:** Haiku (structured interpretation task — cheap and fast).

### 4 — Execution subagents

Once planning is complete, each item in the final `mutation_plan` is dispatched to a typed execution subagent (Haiku). Each subagent handles one mutation and produces the correct operation JSON for its type:

- `update_plan` — modify task lists for an anchor
- `update_context` / `append_context` / `patch_context` — modify context entries
- `update_anchor` — modify anchor fields
- `chat` — no DB mutation, just a response

### 5 — Satisfaction evaluator

After all mutations execute, a satisfaction evaluator (Haiku) checks whether the mutations actually accomplished the orchestrator's stated intent. If not, the pipeline re-enters the planning loop (max 2 retries).

### 6 — Response builder

Produces the final user-facing message (Sonnet). Receives the post-mutation state, subagent reports, and conversation history.

## Model assignments

| Stage | Model | Reason |
|-------|-------|--------|
| Quick classifier | Haiku | Fast binary routing |
| Orchestrator | Sonnet | Reasoning quality — sets the intent |
| Meta-evaluator | Haiku | Structured interpretation — cheap + fast |
| Execution subagents | Haiku | Well-scoped atomic tasks |
| Satisfaction eval | Haiku | Binary judgment against clear criteria |
| Response builder | Sonnet | User-facing — tone and quality matter |

Model assignments are configurable in `config/app_config.yaml` under `models:`.

## Pipeline constants

| Constant | Default | What it controls |
|----------|---------|-----------------|
| `HISTORY_EXCHANGES` | 5 | Conversation turns fed to orchestrator |
| `MAX_PLANNING_ROUNDS` | 4 | Orchestrator ↔ meta-evaluator iterations |
| `MAX_REPAIR_ATTEMPTS` | 3 | Meta-evaluator JSON repair retries |
| `MAX_SATISFACTION_RETRIES` | 2 | Mutation satisfaction re-checks |

## Prompt templates

All prompts are Jinja2 markdown templates in `prompts/`:

| File | Stage |
|------|-------|
| `orchestrator.md` | Orchestrator reasoning |
| `meta_eval.md` | Meta-evaluator intent translation |
| `meta_eval_repair.md` | JSON repair on malformed meta-eval output |
| `subagent_upsert.md` | Execution: full-replacement mutations |
| `subagent_patch.md` | Execution: targeted edit mutations |
| `satisfaction_eval.md` | Post-execution satisfaction check |
| `response_builder.md` | Final user-facing message |
| `quick_classifier.md` | Quick vs full routing |
