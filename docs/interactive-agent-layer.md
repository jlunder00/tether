# Interactive Agent Layer — Architecture Notes

This document describes the cross-process event delivery model for the interactive agent layer service (`tether/interactive_agent_layer/`).

## Process boundary

The interactive agent layer runs as a separate supervisord program from the API service:

```ini
# supervisord.conf
[program:interactive-agent-layer]   # port 5003 — its own OS process
[program:tether-api]                 # port 8000 — separate OS process
```

Each supervisord program is an independent OS process with its own event loop and memory space. Co-location does not mean in-process. The in-process `WSPublisher` (asyncio queues) cannot deliver events across this boundary.

## Active-turn events: SSE → dispatch event_fn → WebSocket

Events generated **during an active agent turn** (while `POST /session/{id}/turn` is streaming) flow cross-process via HTTP:

```
layer (process A)
  ↓  yields on /session/{id}/turn SSE stream
dispatch / bot handler (process A or B)
  ↓  LayerClient.turn() reads SSE incrementally (no buffering)
  ↓  event_fn callback fires per event
API /ws handler (process B)
  ↓  forwards to open WebSocket connection
frontend
```

Event types delivered this way:

| Event | When |
|---|---|
| `agent_text_delta` | Streaming text fragment |
| `agent_action` | Tool-use translated to friendly phrase |
| `permission_request` | User approval prompt (user_action tools) |
| `status` | Pipeline status update |
| `turn_complete` | Turn finished |
| `session_ended` | Session terminated or interrupted |
| `trial_usage_update` | Live trial count (2.5, free-tier) |

`permission_request` was wired onto the SSE stream in Wave 4 (PR #394). `PermissionGate` enqueues events into an `outbound_events: asyncio.Queue` that `run_turn` drains alongside pool SSE events, yielding them on the turn stream.

## Background events: Redis pub/sub via WSPublisher dual-write

Events fired **outside an active turn** (background lifecycle, async quota updates) cannot use the SSE stream. These use Redis pub/sub (PR #404):

```
WSPublisher.push()
  ├─ in-process asyncio queues  → in-process subscribers (tests, co-located callers)
  └─ Redis PUBLISH tether:ws:{user_ws_id}  → API /ws handler subscribes → WebSocket
```

- **In-process path** is preserved — tests and local dev work without Redis
- **Graceful degradation** when `REDIS_URL` is absent — Redis publish silently skipped
- **Channel key:** `tether:ws:{user_ws_id}`

## Permission round-trip

```
pool control_request SSE
  ↓  session.run_turn() sees event == "control_request"
  ↓  asyncio.create_task(_handle_control_request)
  ↓  PermissionGate.can_use_tool() → puts permission_request in outbound_events queue
  ↓  _drain_until_done() yields permission_request on turn SSE stream
  ↓  dispatch event_fn → user WebSocket → frontend shows Approve/Deny
user clicks
  ↓  POST /permission/{request_id}/respond → layer HTTP API
  ↓  resolves asyncio.Future in session.permission_pending
  ↓  PermissionGate returns Allow/Deny
  ↓  send_control_response to pool → pool unblocks can_use_tool callback
  ↓  SDK proceeds or skips the tool call
```
