# Bot WebSocket Authentication

The Tether API WebSocket endpoint (`/ws`) supports two authentication patterns:

## Cookie-based (browser clients)

The browser sends a `tether_token` cookie with a valid JWT. Authentication is validated before the connection is established.

## Message-based (bot clients)

For bot processes that cannot use cookies (e.g., the `tether-premium` scheduling bot running as a service), the WebSocket supports message-based authentication:

1. Connect to `/ws` without a cookie.
2. As the **first message**, send:
   ```json
   {"type": "auth", "token": "<jwt>"}
   ```
3. The server validates the JWT. On success, the connection is kept open and the bot can receive broadcast events. On failure, the server closes with code `1008`.

The JWT must be generated with the same secret used by the API (`AUTH_SECRET` env var or config). The `user_id` claim in the payload identifies which user's events the connection receives.

### Timeout

If no auth message is received within 10 seconds of connection, the server closes with code `1008`.

### Example (Python)

```python
import asyncio
import json
import websockets

async def connect_bot(api_base: str, token: str):
    uri = api_base.replace("http", "ws") + "/ws"
    async with websockets.connect(uri) as ws:
        await ws.send(json.dumps({"type": "auth", "token": token}))
        async for msg in ws:
            event = json.loads(msg)
            print("Received:", event)
```
