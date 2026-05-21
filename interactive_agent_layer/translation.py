"""Translation table for agent tool events.

Maps tool names to typed translation entries. BackgroundEntry and
BackgroundHiddenEntry intentionally have no permission fields so that
internal detail cannot be accidentally surfaced to users.
"""
from __future__ import annotations

import dataclasses
import pathlib
from typing import Union

import yaml


@dataclasses.dataclass(frozen=True)
class BackgroundEntry:
    type: str  # "background"
    phrase: str


@dataclasses.dataclass(frozen=True)
class BackgroundHiddenEntry:
    type: str  # "background_hidden"
    phrase: str


@dataclasses.dataclass(frozen=True)
class PassthroughEntry:
    type: str  # "passthrough"


@dataclasses.dataclass(frozen=True)
class UserActionEntry:
    type: str  # "user_action"
    phrase_short: str
    permission_summary: str
    permission_detail_field: str


TranslationEntry = Union[BackgroundEntry, BackgroundHiddenEntry, PassthroughEntry, UserActionEntry]


class TranslationTable:
    def __init__(self, entries: dict[str, TranslationEntry]) -> None:
        self._entries = entries

    @classmethod
    def from_yaml(cls, path: "pathlib.Path | str | None" = None) -> "TranslationTable":
        """Load from YAML file. Defaults to config/agent_translations.yaml."""
        if path is None:
            path = pathlib.Path(__file__).parent.parent / "config" / "agent_translations.yaml"
        raw = yaml.safe_load(pathlib.Path(path).read_text())
        entries: dict[str, TranslationEntry] = {}
        for name, data in raw.items():
            entries[name] = _parse_entry(data)
        return cls(entries)

    def lookup(self, tool_name: str) -> TranslationEntry:
        """Return entry for tool_name, falling back to _unknown."""
        return (
            self._entries.get(tool_name)
            or self._entries.get("_unknown")
            or BackgroundEntry(type="background", phrase="Working")
        )

    def interpolate_phrase(self, entry: TranslationEntry, args: dict) -> str:
        """Interpolate the phrase with tool args. Uses format_map with forgiving fallback."""
        if isinstance(entry, PassthroughEntry):
            return ""
        if isinstance(entry, UserActionEntry):
            phrase = entry.phrase_short
        else:
            phrase = entry.phrase
        try:
            return phrase.format_map(ForgivingMap(args))
        except Exception:
            return phrase


class ForgivingMap(dict):
    """dict subclass that returns '{key}' for missing keys instead of raising KeyError."""

    def __missing__(self, key: str) -> str:
        return f"{{{key}}}"


def _parse_entry(data: dict) -> TranslationEntry:
    t = data["type"]
    if t == "background":
        return BackgroundEntry(type=t, phrase=data["phrase"])
    if t == "background_hidden":
        return BackgroundHiddenEntry(type=t, phrase=data["phrase"])
    if t == "passthrough":
        return PassthroughEntry(type=t)
    if t == "user_action":
        return UserActionEntry(
            type=t,
            phrase_short=data["phrase_short"],
            permission_summary=data["permission_summary"],
            permission_detail_field=data["permission_detail_field"],
        )
    raise ValueError(f"Unknown translation entry type: {t!r}")
