from __future__ import annotations
import re
from dataclasses import dataclass, field

_DB_COMMANDS: frozenset[str] = frozenset({"check-in", "tether-update-context", "update-plan"})
_SKIP_COMMANDS: frozenset[str] = frozenset({"start", "link", "stop"})

_DB_PATTERN = re.compile(
    r"^/(check-in|tether-update-context|update-plan)",
    re.MULTILINE,
)
_SLASH_PATTERN = re.compile(r"/([a-z][a-z0-9-]+)")


@dataclass
class SlashParseResult:
    db_commands_applied: list[str] = field(default_factory=list)
    skill_commands: list[str] = field(default_factory=list)
    clean_text: str = ""


def scan_slash_commands(text: str, skill_registry: dict | None = None) -> SlashParseResult:
    """Parse slash commands from a message.

    DB commands are only recognised at the start of a line.
    Skill commands are found anywhere in the text.
    """
    db_commands = [m.group(1) for m in _DB_PATTERN.finditer(text)]

    all_slash = [m.group(1) for m in _SLASH_PATTERN.finditer(text)]
    skill_candidates = [
        cmd for cmd in all_slash
        if cmd not in _DB_COMMANDS and cmd not in _SKIP_COMMANDS
    ]

    if skill_registry is not None:
        skill_candidates = [cmd for cmd in skill_candidates if f"/{cmd}" in skill_registry]

    return SlashParseResult(
        db_commands_applied=db_commands,
        skill_commands=skill_candidates,
        clean_text=text,
    )
