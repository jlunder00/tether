"""Agent pool manager configuration — loaded from TetherConfig agent_pool block."""
from __future__ import annotations

from dataclasses import dataclass, field, fields


@dataclass
class AgentPoolConfig:
    """Configuration for the agent pool manager.

    All values correspond to the ``agent_pool:`` block in app_config.yaml.
    Defaults match the Fly ``shared-cpu-1x`` 512 MB tuning targets.
    """

    target_depth_per_hash: int = 2
    """Warm subprocesses to keep per options_hash partition."""

    capacity_total: int = 8
    """Maximum total subprocesses across all partitions (warm + active + warming)."""

    max_age_seconds: int = 600
    """TTL for warm subprocesses — drained on next acquire if exceeded."""

    refill_poll_interval: float = 2.0
    """Seconds between refill loop checks."""

    prime_timeout_seconds: int = 30
    """Max seconds to wait for a priming response."""

    acquire_default_timeout: int = 10
    """Default acquire timeout when caller omits timeout_seconds."""

    base_url: str = "http://127.0.0.1:5002"
    """Base URL for the PoolClient (callers) to reach the pool service."""

    enabled: bool = True
    """False → callers fall back to direct ClaudeSDKClient spawn (for local dev)."""

    control_response_timeout_seconds: float = 60.0
    """Seconds the pool waits for a control_response before denying the tool call."""


_FIELD_NAMES = {f.name for f in fields(AgentPoolConfig)}


def load_pool_config(tether_config: object) -> AgentPoolConfig:
    """Build an AgentPoolConfig from a TetherConfig instance.

    Only keys present in the dataclass are consumed; unknown keys are ignored.
    """
    try:
        raw: dict = tether_config.get("agent_pool", {})  # type: ignore[attr-defined]
    except Exception:
        raw = {}

    known = {k: v for k, v in raw.items() if k in _FIELD_NAMES}
    return AgentPoolConfig(**known)
