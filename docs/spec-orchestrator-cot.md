# Spec: Orchestrator CoT Improvements

## Problem

The current orchestrator has two weaknesses:

1. **No conversation history.** Every message is stateless. The bot has no memory of the last few exchanges, so when it gets something wrong, the user has to restate everything from scratch.

2. **One-shot planning.** `think_and_plan` sees a list of context subjects but no content. It must commit to a dispatch plan without being able to read anything. The result is vague instructions to subagents and subagents that fail or produce shallow results.

---

## Solution Overview

Three changes, in priority order:

1. **Conversation history** — store recent message/response pairs in SQLite; inject into orchestrator prompts
2. **Multi-turn context request loop** — `think_and_plan` becomes iterative; before committing to dispatches the orchestrator can request anchor info, plan details, or specific context entries; the message handler feeds back the requested data and re-invokes
3. **DB-backed instruction staging** — orchestrator writes and patches its subagent instructions as a planning entry before finalizing the dispatch, enabling inspection and retry from a known state

A fourth piece — a **summarizer middleman** for compressing long context chains — is specified but deferred.

---

## 1. Conversation History

### DB schema addition

```sql
CREATE TABLE IF NOT EXISTS conversation_history (
    id        INTEGER PRIMARY KEY AUTOINCREMENT,
    role      TEXT NOT NULL,   -- 'user' | 'assistant'
    body      TEXT NOT NULL,
    ts        DATETIME DEFAULT CURRENT_TIMESTAMP
);
```

### Behavior

- After every successful `handle_message`, append the user message and final bot response to `conversation_history`.
- On each new message, read the last `N=5` exchange pairs (10 rows) ordered by `ts DESC`, reverse for chronological order.
- Inject as a `## Recent conversation` block into `think_and_plan.md` and `orchestrator_response.md`.
- Do **not** inject history into subagent prompts — they already receive precise instructions from the orchestrator.

### Format injected into prompts

```
## Recent conversation (last 5 exchanges)
[2026-03-28 14:02] User: move my grind tasks to Sunday
[2026-03-28 14:02] Bot: Done — moved Apply to 3 jobs and Leetcode to Sunday grind_am.
[2026-03-28 14:05] User: actually keep leetcode today
[2026-03-28 14:05] Bot: Kept Leetcode in today's grind_am. Sunday grind_am now has Apply to 3 jobs only.
```

---

## 2. Multi-turn Context Request Loop

### Motivation

The orchestrator needs to read context entry bodies, specific dates' plans, and anchor details before it can write useful subagent instructions. Right now it guesses. The fix: let it ask.

### New structured output type: `request_context`

Instead of always returning `{ack, dispatches}`, `think_and_plan` may return:

```json
{
  "type": "request_context",
  "requests": [
    {"kind": "context_entry", "subject": "Intellipat"},
    {"kind": "plan",          "date": "2026-03-30"},
    {"kind": "anchor_detail", "anchor_id": "grind_am"},
    {"kind": "check_in_log",  "date": "2026-03-28"}
  ],
  "reason": "Need Intellipat status and Sunday's plan before I can write instructions."
}
```

Supported `kind` values:

| kind | payload fields | what gets returned |
|------|---------------|--------------------|
| `context_entry` | `subject` | full body of that context entry (prefix match, returns all children too) |
| `plan` | `date` (YYYY-MM-DD, defaults to today) | full plan for that date |
| `anchor_detail` | `anchor_id` | anchor record (id, name, time, duration) |
| `check_in_log` | `date` (defaults to today) | array of check-in rows for that date |

### Loop in `handle_message`

```python
MAX_CONTEXT_ROUNDS = 4   # caps request_context iterations
accumulated_context: list[str] = []

for round_num in range(MAX_CONTEXT_ROUNDS + 1):
    raw_result = think_and_plan(
        user_message, anchors, all_subjects, db_path,
        extra_context=accumulated_context,
        round_num=round_num,
    )

    if raw_result["type"] == "request_context":
        if round_num == MAX_CONTEXT_ROUNDS:
            # Force a dispatch on the final round regardless
            raw_result = think_and_plan(
                user_message, anchors, all_subjects, db_path,
                extra_context=accumulated_context,
                round_num=round_num,
                force_dispatch=True,
            )
            break
        fetched = _fetch_requested_context(raw_result["requests"], db_path)
        accumulated_context.append(fetched)
        continue

    # type == "dispatch"
    break

_orchestrate(user_message, raw_result["dispatches"], raw_result.get("ack"), db_path, send_fn)
```

`_fetch_requested_context` returns a formatted string block:

```
## Fetched context (round 2)

### Context: Intellipat
<full body>

### Plan: 2026-03-30
<plan for that date>
```

### Prompt changes to `think_and_plan.md`

Add to the prompt:

```
## Accumulated context (from prior requests this round)
{{ extra_context }}   {# empty string on round 0 #}

---

You may either:
(a) Request more context — if you need to read a context entry body, a specific date's plan, anchor details, or check-in log before you can write good instructions.
(b) Commit to dispatches — when you have enough to write precise subagent instructions.

If requesting context, respond:
{"type": "request_context", "requests": [...], "reason": "..."}

If dispatching, respond:
{"type": "dispatch", "ack": "...", "dispatches": [...]}

Do NOT request context you already have above. Max {{ max_rounds - round_num }} more request rounds available.
```

The existing dispatch schema is unchanged — just wrapped in `"type": "dispatch"`.

### `force_dispatch` flag

When `force_dispatch=True`, add to the prompt:

```
This is your final round. You MUST respond with type "dispatch" regardless of what context is missing. Do your best with what you have.
```

---

## 3. DB-backed Instruction Staging

### Motivation

Let the orchestrator prepare subagent instructions as a DB entry, patch them iteratively, and only dispatch once satisfied. This makes the planning visible in the UI and enables robust retry.

### New mutation op: `stage_instructions`

```json
{"op": "stage_instructions", "dispatch_id": "move_grind_tasks", "body": "..."}
```

Written to subject `Bot/Staging/<dispatch_id>`. These entries are ephemeral — cleared at the start of each `handle_message`.

### New structured output type: `prepare`

The orchestrator can return this during the context request loop (not yet ready to dispatch):

```json
{
  "type": "prepare",
  "mutations": [
    {"op": "stage_instructions", "dispatch_id": "update_grind_am", "body": "Draft instructions..."}
  ],
  "continue": true
}
```

After the message handler applies the `stage_instructions` mutations, it re-invokes `think_and_plan` with the staged entries injected as extra context, allowing the orchestrator to read and patch its own draft before committing.

When ready to dispatch, the orchestrator can reference a staged entry:

```json
{
  "type": "dispatch",
  "ack": "Updating grind_am as discussed.",
  "dispatches": [
    {
      "action": "update_plan",
      "anchor_id": "grind_am",
      "instructions_from_staging": "Bot/Staging/update_grind_am"
    }
  ]
}
```

The message handler reads `Bot/Staging/update_grind_am` and passes its body as the `instructions` field to the subagent.

**Note:** This feature is additive — the orchestrator can still write `instructions` inline. Staging is only needed when the orchestrator wants to iterate before finalizing.

---

## 4. Summarizer Middleman (deferred)

### When to build

After step 3 is live and we can observe real token usage. Build if accumulated context chains routinely exceed ~6000 tokens before dispatch.

### Design

When `len(accumulated_context_string) > TOKEN_THRESHOLD`:

1. Invoke a cheap summarizer call with the full context chain + user message
2. Summarizer returns a compact briefing: current state, relevant facts, what the user is asking
3. Replace `accumulated_context` with the summary before building subagent prompts
4. Log the original chain to `Bot/Staging/summary_source` for debugging

The summarizer is a single `claude -p` call with a short timeout (20s). If it fails, fall through to the unsummarized chain.

---

## Implementation Order

### Phase A — Conversation history
**Files:** `db/schema.py`, `db/queries.py`, `bot/message_handler.py`, `prompts/think_and_plan.md`, `prompts/orchestrator_response.md`

1. Add `conversation_history` table to schema
2. Add `insert_conversation_turn(db, role, body)` and `get_recent_history(db, n=5)` queries
3. In `handle_message`: load history before orchestration, append user+bot turn after
4. Inject formatted history block into `think_and_plan` and `orchestrator_response` templates

### Phase B — Multi-turn context request loop
**Files:** `bot/message_handler.py`, `prompts/think_and_plan.md`

1. Add `_fetch_requested_context(requests, db_path) -> str`
2. Refactor `think_and_plan` to accept `extra_context` and `force_dispatch` params
3. Replace the `think_and_plan` call in `handle_message` with the loop
4. Update `think_and_plan.md` with the dual-mode schema and accumulated context section
5. Handle `force_dispatch` in the prompt

### Phase C — DB-backed instruction staging
**Files:** `bot/message_handler.py`, `db/queries.py`, `prompts/think_and_plan.md`

1. Add `stage_instructions` mutation op to `apply_mutations`
2. Clear `Bot/Staging/*` entries at start of each `handle_message`
3. Handle `type: "prepare"` in the loop: apply staging mutations, re-invoke with staged entries as extra context
4. Handle `instructions_from_staging` in `_build_dispatch_prompt`
5. Update prompt to document the `prepare` type and staging pattern

### Phase D — Summarizer (deferred)
After observing real token usage from Phase C.

---

## Non-goals

- Subagents do NOT get the conversation history or accumulated context — they receive only their specific instructions and the data they need to execute. Keep them narrow.
- The context request loop is for the orchestrator only. Subagent retry (the existing `_evaluate_completion` loop) is separate and unchanged.
- Do not persist staging entries across messages — they are scratch space, cleared each run.
