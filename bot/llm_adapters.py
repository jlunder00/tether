"""Tool schema adapters: canonical Anthropic format → vendor-specific format.

Canonical schema (Anthropic shape):
  {
    "name": "tool_name",
    "description": "what it does",
    "input_schema": { "type": "object", "properties": {...} }
  }
"""


def to_anthropic_schema(tool: dict) -> dict:
    """Pass-through — canonical IS Anthropic's format."""
    return tool


def to_openai_schema(tool: dict) -> dict:
    """Convert canonical → OpenAI function-calling format."""
    return {
        "type": "function",
        "function": {
            "name": tool["name"],
            "description": tool.get("description", ""),
            "parameters": tool["input_schema"],
        },
    }


def to_bedrock_schema(tool: dict) -> dict:
    """Convert canonical → AWS Bedrock converse API toolSpec format."""
    return {
        "toolSpec": {
            "name": tool["name"],
            "description": tool.get("description", ""),
            "inputSchema": {
                "json": tool["input_schema"],
            },
        }
    }
