"""Redis channel name helpers shared across processes.

Both the interactive-agent-layer (publisher) and the API (subscriber)
must agree on the channel key format. Define it once here.

Channel key: ``user:{user_id}:events``

The ``user_id`` is the stable JWT claim. It is distinct from
``user_ws_id`` (the per-connection identifier used by WSPublisher's
in-process queues). Using ``user_id`` for the Redis channel means
the API subscriber can derive the correct channel from the JWT alone,
without needing to know the per-connection identifier.
"""
from __future__ import annotations

_CHANNEL_PREFIX = "user"


def channel_for(user_id: str) -> str:
    """Return the Redis channel name for a user's events."""
    return f"{_CHANNEL_PREFIX}:{user_id}:events"
