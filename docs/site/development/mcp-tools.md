# MCP Tools

Tether exposes MCP tools over SSE on port 5001.

## Connecting

Add to your Claude Code MCP config:

```json
{
  "mcpServers": {
    "tether": {
      "url": "http://localhost:5001/sse",
      "headers": {
        "X-API-Key": "your-api-key"
      }
    }
  }
}
```

Generate an API key from the Tether web interface under Settings → API Keys.

## Tools

<!-- TODO: Document all tools with parameters, return shapes, and write modes. Source: tether/tether_mcp/server.py -->

*Full tool reference coming soon.*
