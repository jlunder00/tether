**You are invoked via `claude -p`. You have no tool access. Produce only JSON output.**

The meta-evaluator produced output that could not be parsed as JSON. Your job is to fix it and return only valid JSON.

## Malformed output
{{ malformed_output }}

## Expected JSON schema
```json
{
  "summary": "string",
  "context_to_fetch": [
    {"kind": "plan|context_entry|anchor_detail", "date"?: "YYYY-MM-DD", "subject"?: "string", "anchor_id"?: "string"}
  ],
  "mutation_plan": [
    {
      "id": "string",
      "type": "update_plan_tasks|update_context|append_context|patch_context|update_anchor|chat",
      "description": "string"
      // plus type-specific fields — preserve ALL fields from the malformed output, do not drop them
    }
  ],
  "orchestrator_done": true | false
}
```

## Context behind this output (orchestrator's reasoning)
{{ orchestrator_conversation }}

## Valid values — use ONLY these when fixing references
**Valid context subjects:** {{ valid_subjects }}
**Valid anchor IDs:** {{ valid_anchor_ids }}
**Available plan dates:** {{ available_dates }}

### Type-specific fields (MUST be preserved or reconstructed from orchestrator context)

**update_plan_tasks:** `"anchor_id": "<id>", "date": "YYYY-MM-DD", "tasks": [{"id": "<uuid or null>", "text": "<text>", "status": "pending|in_progress|done|skipped|blocked"}]`

**update_context:** `"subject": "<exact subject>", "body": "<full new body>"`

**append_context:** `"subject": "<exact subject>", "content": "<text to append>"`

**patch_context:** `"subject": "<exact subject>", "old": "<text to find>", "new": "<replacement>"`

**update_anchor:** `"anchor_id": "<anchor id>", "fields": {"time"?: "HH:MM", "name"?: "string", "duration_minutes"?: number}`

**chat:** `"message": "<text to send to user>"`

---

Common failure modes to fix:
- Hallucinated subject name or anchor ID → replace with the closest valid match from the lists above
- Truncated or incomplete JSON → complete the structure using the orchestrator conversation as the source of truth for parameter values
- Markdown fences or extra text → strip everything except the JSON object
- Trailing commas, unquoted keys, single quotes → fix to valid JSON
- **Missing type-specific fields** (anchor_id, tasks, subject, body, content, etc.) → reconstruct them from the orchestrator conversation; a mutation without its required params is useless and must be completed, not omitted

Return only the corrected JSON object. No explanation, no fences.
