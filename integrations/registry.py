"""Provider registry — maps provider name strings to their classes.

The sync worker dispatches based on the `provider` column in user_integrations,
so it uses this registry to look up the right SyncProvider class at runtime.
"""
from __future__ import annotations

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from integrations.base import OAuthProvider, SyncProvider

_registry: dict[str, dict] = {}


def register(
    name: str,
    oauth_cls: type | None = None,
    sync_cls: type | None = None,
) -> None:
    """Register provider classes under *name*."""
    _registry[name] = {"oauth": oauth_cls, "sync": sync_cls}


def get_oauth(name: str) -> type["OAuthProvider"]:
    """Return the OAuthProvider class for *name*, or raise KeyError."""
    entry = _registry.get(name)
    if not entry or not entry.get("oauth"):
        raise KeyError(f"No OAuth provider registered for '{name}'")
    return entry["oauth"]


def get_sync(name: str) -> type["SyncProvider"]:
    """Return the SyncProvider class for *name*, or raise KeyError."""
    entry = _registry.get(name)
    if not entry or not entry.get("sync"):
        raise KeyError(f"No sync provider registered for '{name}'")
    return entry["sync"]


def list_providers() -> list[str]:
    return list(_registry.keys())
