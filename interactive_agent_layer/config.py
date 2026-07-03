"""Config helpers for the interactive agent layer."""
from __future__ import annotations

from config.loader import config


def get_base_url() -> str:
    return config.get("agent_layer.base_url", "http://127.0.0.1:5003")


def is_enabled() -> bool:
    return bool(config.get("agent_layer.enabled", True))


def get_permission_timeout() -> int:
    return int(config.get("agent_layer.permission_timeout_seconds", 900))


def get_auto_approve_user_actions() -> bool:
    return bool(config.get("agent_layer.auto_approve_user_actions", False))


def get_trial_monthly_quota() -> int:
    """Maximum tether-agent-2.5 sessions per free-tier user per calendar month."""
    return int(config.get("agent_layer.trial_monthly_quota", 10))


def get_leaky_providers() -> list[str]:
    """Providers whose dashboards expose prompt content — 2.5 is disabled on these."""
    return list(config.get("agent_layer.leaky_providers", ["openrouter", "openai"]))


def get_scope_radius() -> int:
    """Default M (hop radius) for read_context scope gating.

    Used when a session doesn't set scope_radius explicitly in options —
    e.g. when scope_source_node_id is resolved from the conversation's
    context_node_id at session-start rather than passed in by the caller.
    """
    return int(config.get("agent_layer.scope_radius", 3))
