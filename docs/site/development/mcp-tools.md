# MCP Tools

Tether exposes 9 intent-based MCP tools over SSE on port 5001. These replace the legacy 38-tool surface with a smaller, more capable set.

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

<!-- TODO: Document all 9 tools with parameters, return shapes, and write modes.
     Source: tether/tether_mcp/server.py + cc-context-store/tether/docs/mcp/mcp-consolidation-spec.md -->

*Full tool reference coming soon.*
