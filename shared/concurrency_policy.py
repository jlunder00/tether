"""Conflict resolution policy for concurrent writers.

Defines what happens when two sources (bot, MCP, UI, beacon) attempt
overlapping writes simultaneously. Stubs here; policy table filled during
bot-intelligence implementation phases.
"""

from __future__ import annotations
from enum import Enum
from shared.scopes import WriteScope, scope_intersects


class ConflictAction(Enum):
    ALLOW = "allow"          # both proceed — last write wins
    QUEUE = "queue"          # incoming waits for active to finish
    REJECT = "reject"        # incoming rejected with StaleReadError-style 409
    MERGE = "merge"          # attempt field-level merge (future)


# (incoming_source, active_source) → ConflictAction
# Stub: all pairs default to QUEUE until bot-intelligence phases populate this.
POLICY_TABLE: dict[tuple[str, str], ConflictAction] = {}


def lookup_policy(incoming_source: str, active_source: str) -> ConflictAction:
    key = (incoming_source, active_source)
    return POLICY_TABLE.get(key, ConflictAction.QUEUE)


def resolve_conflict(
    incoming: WriteScope,
    active: WriteScope,
) -> ConflictAction:
    if not scope_intersects(incoming, active):
        return ConflictAction.ALLOW
    return lookup_policy(incoming.op_class, active.op_class)
