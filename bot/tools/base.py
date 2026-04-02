"""Base classes for the tool plugin system."""
from dataclasses import dataclass, field
from typing import Callable, Awaitable, Any


class ToolResult:
    def __init__(self, ok: bool, content: str):
        self.ok = ok
        self.content = content

    @staticmethod
    def ok(content: str) -> "ToolResult":
        return ToolResult(True, content)

    @staticmethod
    def error(content: str) -> "ToolResult":
        return ToolResult(False, content)

    def __repr__(self):
        return f"ToolResult(ok={self.ok}, content={self.content!r})"


@dataclass
class Tool:
    name: str
    description: str
    input_schema: dict
    execute: Callable[[dict, Any], Awaitable[ToolResult]]
    read_only: bool = True
    guardrails: list[str] = field(default_factory=list)

    def to_api_schema(self) -> dict:
        """Canonical schema shape for LLM backends."""
        return {
            "name": self.name,
            "description": self.description,
            "input_schema": self.input_schema,
        }
