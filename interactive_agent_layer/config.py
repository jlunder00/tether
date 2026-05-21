"""Config helpers for the interactive agent layer."""
from __future__ import annotations

from config.loader import config


def get_base_url() -> str:
    return config.get("agent_layer.base_url", "http://127.0.0.1:5003")


def is_enabled() -> bool:
    return bool(config.get("agent_layer.enabled", True))


def get_permission_timeout() -> int:
    return int(config.get("agent_layer.permission_timeout_seconds", 60))
