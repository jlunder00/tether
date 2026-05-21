"""Pool client for the interactive agent layer.

Re-exports the real PoolClient from agent_pool_manager so callers import
from a single location and the layer stays decoupled from the pool service's
internal package structure.
"""
from __future__ import annotations

from agent_pool_manager.client import PoolClient, PoolClientError

__all__ = ["PoolClient", "PoolClientError"]
