"""Write scope primitives for multi-source concurrency control.

A WriteScope describes which data a bot/agent turn intends to modify.
Populated by bot-intelligence phases; stubs here establish the interface.
"""

from __future__ import annotations
from dataclasses import dataclass, field


@dataclass(frozen=True)
class WriteScope:
    """Describes the set of resources a write operation touches."""
    resource_type: str          # "tasks" | "context" | "anchors" | "schedule" | "*"
    resource_ids: frozenset[str] = field(default_factory=frozenset)
    op_class: str = "human_edit"  # scheduling | brain_dump | human_edit | review | beacon

    @classmethod
    def all(cls, op_class: str = "human_edit") -> "WriteScope":
        return cls(resource_type="*", op_class=op_class)


def scope_intersects(a: WriteScope, b: WriteScope) -> bool:
    """True if both scopes touch overlapping resources."""
    if a.resource_type == "*" or b.resource_type == "*":
        return True
    if a.resource_type != b.resource_type:
        return False
    if not a.resource_ids or not b.resource_ids:
        return True  # unspecified IDs = potentially all
    return bool(a.resource_ids & b.resource_ids)


def scope_contains(outer: WriteScope, inner: WriteScope) -> bool:
    """True if outer fully covers inner."""
    if outer.resource_type == "*":
        return True
    if outer.resource_type != inner.resource_type:
        return False
    if not outer.resource_ids:
        return True
    return inner.resource_ids <= outer.resource_ids
