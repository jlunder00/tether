You are evaluating whether a set of subagent tasks was completed successfully for Tether, an ADHD accountability bot.

## Today: {{ date }}

## Original user request
{{ user_message }}

## Original dispatch plan
{{ original_dispatches }}

## Subagent reports (all rounds so far)
{% for report in all_reports %}
- {{ report }}
{% endfor %}

## Current plan state (after all mutations applied)
{% for anchor_id, anchor_data in plan.anchors.items() %}
### {{ anchor_id }}
{% for task in anchor_data.tasks %}- {{ task }}
{% endfor %}{% else %}(No tasks)
{% endfor %}

## Anchors (with IDs)
{{ anchors }}

---

Respond with JSON only — no explanation, no markdown fences.

Assess whether the original request was fully completed. If anything is missing or failed, produce corrected dispatch instructions for the remaining work.

```
{
  "complete": true | false,
  "assessment": "One sentence: what was done and what (if anything) is still missing.",
  "remaining_dispatches": [
    {
      "action": "update_plan" | "update_context" | "update_anchor" | "chat",
      "anchor_id": "<exact anchor id from the list above>",
      "date": "YYYY-MM-DD",
      "subjects": [],
      "prefetch_date": "YYYY-MM-DD",
      "instructions": "Specific corrected instructions for what still needs to happen."
    }
  ]
}
```

Rules:
- `complete: true` if the plan state above matches what the user asked for
- `remaining_dispatches` is ONLY populated if `complete` is false
- Use exact anchor IDs from the anchor list above — never invent them
- Be conservative: if a FAILED report is present for a task, include it in remaining_dispatches with corrected instructions
