# API Reference

<!-- TODO: Flesh out with full route documentation. Sources: tether/api/routes/, tether/api/main.py -->

## Base URL

```
http://localhost:8000   (local development)
```

## Authentication

The API uses JWT cookies for browser clients. For programmatic access (including MCP), use an API key. See [MCP & Claude Code](/using-tether/mcp) for how to generate one.

## WebSocket

The `/ws` endpoint supports real-time event delivery to the frontend.

**Browser clients:** Send a `tether_token` JWT cookie — authentication is validated on connection.

**Bot / service clients:** Connect without a cookie, then send as the first message:

```json
{"type": "auth", "token": "<jwt>"}
```

If no auth message is received within 10 seconds, the server closes with code `1008`.

<!-- TODO: Document all REST endpoints by resource group once the API stabilizes post-config-redesign. -->
