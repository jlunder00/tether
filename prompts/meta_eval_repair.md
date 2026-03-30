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
      "type": "update_plan|update_context|append_context|patch_context|update_anchor|chat",
      "description": "string"
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

---

Common failure modes to fix:
- Hallucinated subject name or anchor ID → replace with the closest valid match from the lists above
- Truncated or incomplete JSON → complete the structure
- Markdown fences or extra text → strip everything except the JSON object
- Trailing commas, unquoted keys, single quotes → fix to valid JSON

Return only the corrected JSON object. No explanation, no fences.
