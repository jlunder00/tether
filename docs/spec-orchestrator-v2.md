# Spec: Orchestrator v2 — Reasoning/Meta-Eval Architecture

## Core Principle

The orchestrator reasons in plain language about what it wants. It never sees mutation syntax,
anchor IDs, or implementation details. A separate meta-evaluator reads the orchestrator's
conversation and handles everything operational: fetching context, building the mutation plan,
deciding when to continue or stop. These two roles never bleed into each other.

---

## Architecture Overview

```
User message
    ↓
[Orchestrator call] — reasons about what it wants, plain language only
    ↓
[Meta-eval call] — interprets orchestrator intent → fetches context, updates mutation plan, decides done?
    ↓
  if not done → inject meta-eval summary + fetched context → loop back to orchestrator
  if done     → staged mutations are final
    ↓
[Typed execution subagents] — one per mutation, each with a specific type (update/create/delete)
    ↓
[Satisfaction eval] — did the mutations accomplish the intent? re-trigger if not
    ↓
[Response builder] — user-facing message
```

Max planning loop iterations: configurable, default 4.
Max satisfaction eval retriggers: 2.

---

## Model Assignment

Model assignments are configurable in `config.yaml` under a `models:` key. This allows
swapping providers (Claude API, OpenAI, Gemini, local models) without touching code.
Each role maps to a named model string that `call_claude()` resolves — when LLM API
support is added, the resolver routes by prefix or config rather than always shelling
out to `claude -p`.

```yaml
models:
  orchestrator:              claude-code-sonnet
  meta_eval:                 claude-code-haiku
  meta_eval_repair:          claude-code-haiku
  meta_eval_repair_escalate: claude-code-sonnet
  execution_subagent:        claude-code-haiku
  satisfaction_eval:         claude-code-haiku
  response_builder:          claude-code-sonnet
```

Current valid values: `claude-code-sonnet`, `claude-code-haiku` (both shell out to
`claude -p` with the appropriate model flag). Future values will include
`claude-api-sonnet`, `openai-gpt4o`, etc. once the API layer is added.

| Role                        | Default              | Reason |
|-----------------------------|----------------------|--------|
| Orchestrator                | claude-code-sonnet   | Reasoning quality matters; it's setting the intent |
| Meta-evaluator              | claude-code-haiku    | Structured interpretation task, cheaper + faster |
| Meta-eval repair            | claude-code-haiku    | Syntax/semantic fix on attempts 1-2 |
| Meta-eval repair escalation | claude-code-sonnet   | Final repair attempt; can reconstruct intent from scratch |
| Execution subagents         | claude-code-haiku    | Well-scoped atomic tasks, no open-ended reasoning |
| Satisfaction eval           | claude-code-haiku    | Binary judgment against clear criteria |
| Response builder            | claude-code-sonnet   | User-facing; tone and quality matter |

---

## Phase 1: The Orchestrator

### What it receives

- Today's date and current anchor
- Today's plan (human-readable, all anchors and tasks)
- Top-level context subjects (names only, no bodies)
- Conversation history (last N exchanges)
- **Meta-eval summary from prior round** (plain English explanation of what was fetched,
  what's staged, and what the meta-eval thinks the orchestrator wants to do next)
- **Fetched context** (full bodies of whatever the meta-eval retrieved this round)
- The user's message

### What it does NOT receive

- Mutation op names or syntax
- Anchor IDs
- DB schema details
- Any instruction on how to trigger dispatch or signal completion

### What it produces

Plain language. No structure required. The orchestrator writes whatever it needs to think
through the request — a sentence, a paragraph, a list of intentions. It does not need to
signal when it's done; the meta-eval determines that.

### Prompt shape (`prompts/orchestrator.md`)

```
You are Tether, an ADHD accountability coach helping {{ user_name }}.

## Today: {{ date }}
## Current block: {{ current_anchor.name }} ({{ current_anchor.time }})

## Today's plan
{{ plan_human_readable }}

## Context topics available
{{ subjects_list }}

## Recent conversation
{{ history }}

{% if meta_eval_summary %}
## What's happening
{{ meta_eval_summary }}

{% endif %}
{% if fetched_context %}
## Context you requested
{{ fetched_context }}

{% endif %}
## User said
{{ user_message }}

---

Think through what the user needs and what you want to do about it.
Write your reasoning and intentions in plain language.
You don't need to worry about how changes get made — focus on what should happen.
```

---

## Phase 2: The Meta-Evaluator

Runs after every orchestrator response. Reads the full orchestrator conversation chain
and the current system state. Produces a structured output that drives everything else.

### What it receives

- Full orchestrator conversation so far (all rounds)
- Current staged mutation plan (what's been decided so far, human-readable)
- Current DB state summary: plan for today + any dates mentioned, context entry subjects,
  what context has already been fetched this session
- Round number and rounds remaining

### What it produces

```json
{
  "summary": "The orchestrator wants to move the grind tasks to Sunday but doesn't have
              Sunday's plan yet. Fetching that now. No mutations staged yet.",

  "context_to_fetch": [
    {"kind": "plan",          "date": "2026-03-30"},
    {"kind": "context_entry", "subject": "Intellipat"}
  ],

  "mutation_plan": [
    {
      "id": "clear-grind-today",
      "type": "update_plan",
      "description": "Clear grind_am tasks on 2026-03-28",
      "anchor_id": "grind_am",
      "date": "2026-03-28",
      "tasks": []
    },
    {
      "id": "set-grind-sunday",
      "type": "update_plan",
      "description": "Set grind_am on 2026-03-30 to the tasks moved from today",
      "anchor_id": "grind_am",
      "date": "2026-03-30",
      "tasks": ["Apply to 3 jobs", "Leetcode"]
    }
  ],

  "orchestrator_done": false
}
```

### The `summary` field

This is the only thing the orchestrator sees from the meta-eval. It must:
- Explain what context was fetched (or that none was needed)
- Describe the current mutation plan in plain English (or "nothing staged yet")
- Note anything ambiguous or missing
- NOT include "orchestrator_done" — that's implicit; if the orchestrator is receiving this
  summary, it means it has another round

The summary is injected as `meta_eval_summary` in the next orchestrator call.

### `orchestrator_done` logic

The meta-eval sets this to `true` when:
- No new context was fetched this round (nothing was missing)
- AND the mutation plan didn't change this round (OR was newly completed with full confidence)
- AND no ambiguities remain

If new context was fetched: always `false` — the orchestrator must see it.
If only the mutation plan was updated: meta-eval's judgment call.
Hard override: if `round_num >= MAX_PLANNING_ROUNDS`, force `true`.

### Mutation plan evolution

The mutation plan is a persistent list that the meta-eval updates each round. It can:
- Add new mutations
- Remove mutations (if the orchestrator changed its mind)
- Update existing mutations (by `id`)

The current plan is passed back to the meta-eval each round as input, so it always has
the full history of what's been decided.

### JSON parse failure recovery

The meta-eval must produce valid JSON on every call. When it doesn't, the following
escalation runs before the planning loop continues:

```
attempt 1-2: haiku repair call
  prompt: "This JSON is malformed. Fix it and return only valid JSON."
  input: raw output + schema reminder
  → if valid: continue normally

attempt 3: sonnet repair call
  same prompt, sonnet instead of haiku
  → if valid: continue normally

if all 3 fail:
  inject error into next orchestrator round:
    meta_eval_summary = "The system had trouble interpreting the last planning step.
                         Please restate what you want to do clearly and concisely."
  orchestrator_done = false, mutation_plan unchanged, no context fetched

session error counter: if parse failures >= 3 in one session:
  abort planning loop, send user:
    "Something went wrong with my planning process. Please try again or rephrase your request."
```

Repair prompt file: `prompts/meta_eval_repair.md`.

The repair call receives:
- Raw malformed output
- The expected JSON schema
- The full orchestrator conversation (so the model understands the intent behind the output)
- Current system state: valid context subjects, valid anchor IDs, available plan dates

The system state is critical — malformed output is often caused by the meta-eval
hallucinating a subject name, anchor ID, or date that doesn't exist. The repair model
needs to know what's actually valid so it can correct the reference, not just fix syntax.
The sonnet repair call (attempt 3) is particularly well-placed to catch this: it has the
orchestrator reasoning chain and can reconstruct a correct plan from intent if the
malformed output is too broken to patch.

### Prompt shape (`prompts/meta_eval.md`)

```
You are the planning interpreter for Tether, an ADHD accountability bot.

Your job: read the orchestrator's conversation and translate its intentions into a
concrete action plan. You handle all the operational details so the orchestrator doesn't have to.

## Orchestrator conversation so far
{{ orchestrator_conversation }}

## Current staged mutation plan
{{ current_mutation_plan_human_readable }}

## What context has already been provided this session
{{ fetched_context_log }}

## System state
- Today: {{ date }}
- Anchors: {{ anchors }}
- Plan dates available: {{ available_dates }}
- Context subjects: {{ all_subjects }}

## Round {{ round_num }} of {{ max_rounds }}

---

Respond with JSON only.

Fields:
- summary: plain English explanation of what you're doing and why (this goes to the orchestrator)
- context_to_fetch: list of {kind, subject/date/anchor_id} — only request what isn't already provided
- mutation_plan: full updated list of planned mutations (include unchanged ones too)
- orchestrator_done: true if the orchestrator has enough to finalize, false if another round is needed

Mutation types allowed in mutation_plan:
- update_plan:     {type, id, description, anchor_id, date, tasks}
- update_context:  {type, id, description, subject, body}     ← full rewrite only if large structural change
- append_context:  {type, id, description, subject, content}
- patch_context:   {type, id, description, subject, old, new}
- update_anchor:   {type, id, description, anchor_id, fields: {time?, name?, duration_minutes?}}
- chat:            {type, id, description, message}            ← no DB changes, just a response
```

---

## Phase 3: Execution Subagents

Once `orchestrator_done` is `true`, each item in the final `mutation_plan` is dispatched
to a typed execution subagent. Each subagent receives:

- Its specific mutation description and parameters from the meta-eval plan
- A plain-English briefing: the meta-eval summary chain (compressed if long) — this is **D**
  from the earlier spec, now implemented naturally
- The relevant DB state for its operation (e.g., current tasks for an update_plan mutation)
- Its type: update / create / delete / chat

The subagent's only job is to produce the correct mutation JSON for its type.
It does not decide what to do — it only decides how to do it correctly given the parameters.

### Typed subagent prompts

Prompts are organized by **operation type**, not by target. Two prompts cover all DB mutations:

**`prompts/subagent_upsert.md`** — handles full-replacement ops: `update_plan_tasks`,
  `update_context`, `update_anchor`. Shape: "here is the target + new values — produce the mutation."

**`prompts/subagent_patch.md`** — handles targeted edit ops: `patch_context`, `append_context`.
  Shape: "here is the target + old/new text — produce the targeted edit."

**`chat` mutations skip subagent dispatch entirely.** A `chat` entry in the mutation plan
is a signal that no DB changes are needed. The response builder already has the full
orchestrator context and handles the reply directly.

Each prompt is short and task-specific. The subagent has no ambiguity about its role.
If delete operations are added in future, they get their own `subagent_delete.md`.

---

## Phase 4: Satisfaction Eval

Runs after all execution subagents complete. Receives:

- The orchestrator's original stated intent (first orchestrator response summarized)
- The meta-eval's final mutation plan description
- The actual DB state post-mutation (relevant anchors/plan/context)
- The subagent reports

Produces:
```json
{
  "satisfied": true,
  "issues": [],
  "replan_needed": false
}
```

If `replan_needed` is true, re-enters the planning loop with a summary of what went wrong
injected as additional context. Max 2 re-plan cycles.

---

## Phase 5: Response Builder

Receives:
- Current state of the plan (post-mutation)
- Subagent reports
- Conversation history
- The user's message

Produces the single user-facing Telegram message. Uses sonnet.

---

## Call Budget

| Scenario | Orchestrator | Meta-eval | Subagents | Sat eval | Response | Total |
|----------|-------------|-----------|-----------|----------|----------|-------|
| Simple chat | 1 | 1 | 1 (chat) | 1 | 1 | **5** |
| Simple mutation | 1 | 1 | 1-2 | 1 | 1 | **5-6** |
| Needs 1 context fetch | 2 | 2 | 1-3 | 1 | 1 | **7-9** |
| Complex planning (3 rounds) | 3 | 3 | 3-5 | 1 | 1 | **11-13** |
| Satisfaction retry | +2 | +2 | +2 | +1 | 0 | +5 |

Compared to current A+B (simple: 5-6, complex: 8-10): comparable for simple cases,
meaningfully more capable for complex ones. Haiku for meta-eval/subagents/sat-eval
keeps cost low — only orchestrator and response builder use sonnet.

---

## DB Changes

### `staging_mutations` table (ephemeral per message)

```sql
CREATE TABLE IF NOT EXISTS staging_mutations (
    id          TEXT PRIMARY KEY,   -- meta-eval assigned id, e.g. "clear-grind-today"
    session_id  TEXT NOT NULL,      -- cleared at start of each handle_message
    type        TEXT NOT NULL,
    description TEXT NOT NULL,
    params_json TEXT NOT NULL,      -- full mutation parameters as JSON
    created_at  DATETIME DEFAULT CURRENT_TIMESTAMP,
    updated_at  DATETIME DEFAULT CURRENT_TIMESTAMP
);
```

Cleared at the start of every `handle_message` call (like the B-phase accumulated context).

### `orchestrator_conversation` table (ephemeral per message)

```sql
CREATE TABLE IF NOT EXISTS orchestrator_conversation (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    session_id  TEXT NOT NULL,
    role        TEXT NOT NULL,   -- 'orchestrator' | 'meta_eval_summary' | 'fetched_context'
    body        TEXT NOT NULL,
    round_num   INTEGER NOT NULL,
    ts          DATETIME DEFAULT CURRENT_TIMESTAMP
);
```

Cleared at the start of every `handle_message`. Used to build the conversation passed to
both the orchestrator (filtered to its own turns + summaries) and the meta-eval (full chain).

---

## Message Handler Loop

```python
session_id = generate_session_id()
clear_session_state(db_path, session_id)

orchestrator_conv: list[dict] = []
current_mutation_plan: list[dict] = []
fetched_context_log: list[str] = []

for round_num in range(MAX_PLANNING_ROUNDS + 1):
    force_done = (round_num == MAX_PLANNING_ROUNDS)

    # Orchestrator call (sonnet)
    orch_response = call_orchestrator(
        user_message=text,
        plan=plan,
        subjects=subjects,
        history=history,
        conversation=orchestrator_conv,       # its prior turns
        meta_eval_summary=last_meta_summary,  # plain english from prior meta-eval
        fetched_context=last_fetched,         # context fetched last round
    )
    orchestrator_conv.append({"role": "orchestrator", "body": orch_response, "round": round_num})

    # Meta-eval call (haiku)
    meta = call_meta_eval(
        orchestrator_conversation=orchestrator_conv,
        current_mutation_plan=current_mutation_plan,
        fetched_context_log=fetched_context_log,
        round_num=round_num,
        force_done=force_done,
    )

    last_meta_summary = meta["summary"]
    current_mutation_plan = meta["mutation_plan"]

    if meta["context_to_fetch"]:
        last_fetched = fetch_requested_context(meta["context_to_fetch"], db_path)
        fetched_context_log.append(last_fetched)
    else:
        last_fetched = ""

    if meta["orchestrator_done"] or force_done:
        break

# Dispatch execution subagents (haiku, one per mutation)
reports = dispatch_typed_subagents(
    mutation_plan=current_mutation_plan,
    orchestrator_summary=summarize_orchestrator_conv(orchestrator_conv),
    db_path=db_path,
)

# Satisfaction eval (haiku)
sat = call_satisfaction_eval(
    original_intent=orchestrator_conv[0]["body"],
    mutation_plan=current_mutation_plan,
    reports=reports,
    db_state=get_relevant_state(db_path, current_mutation_plan),
)
if sat["replan_needed"]:
    # re-enter loop with sat["issues"] injected as context (max 2 times)
    ...

# Response builder (sonnet)
final = call_response_builder(plan, reports, history, text)
send_fn(final)
insert_conversation_turn(db_path, "user", text)
insert_conversation_turn(db_path, "assistant", final)
```

---

## Migration from Current Architecture

The existing `think_and_plan` → dispatch → eval → memory → response pipeline is replaced
entirely. The memory consolidation step is absorbed into the meta-eval's mutation plan
(context updates appear as `append_context`/`patch_context` mutations in the plan) and
executed by the context update subagent.

The existing prompt files (`think_and_plan.md`, `dispatch_handler.md`, `orchestrator_evaluate.md`,
`orchestrator_memory.md`, `orchestrator_response.md`) are retired. New files:

| New file | Replaces |
|----------|----------|
| `prompts/orchestrator.md` | `think_and_plan.md` |
| `prompts/meta_eval.md` | `dispatch_handler.md` + `orchestrator_evaluate.md` + `orchestrator_memory.md` |
| `prompts/meta_eval_repair.md` | (new) |
| `prompts/subagent_upsert.md` | parts of `dispatch_handler.md` (update_plan, update_context, update_anchor) |
| `prompts/subagent_patch.md` | parts of `dispatch_handler.md` (patch_context, append_context) |
| `prompts/satisfaction_eval.md` | `orchestrator_evaluate.md` (partial) |
| `prompts/response_builder.md` | `orchestrator_response.md` (also handles chat mutations) |

---

## Implementation Order

1. DB schema additions (`staging_mutations`, `orchestrator_conversation`)
2. `call_orchestrator()` + `prompts/orchestrator.md`
3. `call_meta_eval()` + `prompts/meta_eval.md`
4. Planning loop in `handle_message`
5. Typed execution subagents (4 prompt files + `dispatch_typed_subagents()`)
6. Satisfaction eval + `prompts/satisfaction_eval.md`
7. Response builder + `prompts/response_builder.md`
8. Remove old pipeline (retire old prompt files, old handler phases)
9. Tests
