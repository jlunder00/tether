"""Provider stub and BYOK leakage helpers for the interactive agent layer.

For v1, all users are on Anthropic OAuth (the only supported provider).
The full provider abstraction — user_settings table, per-user provider
preference, multi-provider support — is future work.

See tether-agent-models spec §"Future provider abstraction" for the planned
design.  When that work lands, replace `get_user_provider` with a real lookup
and wire it to the user_settings table.
"""
from __future__ import annotations

from interactive_agent_layer.config import get_leaky_providers


def get_user_provider(user_id: str) -> str:  # noqa: ARG001
    """Return the active provider for a user.

    STUB: returns 'anthropic_oauth' for all users. Replace with a user_settings
    lookup once the full provider abstraction lands (values will be one of:
    anthropic_oauth, anthropic_api_key, openai, openrouter, local_ollama,
    tether_hosted).
    """
    return "anthropic_oauth"


def is_leaky_provider(provider: str) -> bool:
    """Return True if `provider` exposes prompt content in its dashboard.

    Leaky providers are unsafe for tether-agent-2.5, which uses proprietary
    prompts. The list comes from `agent_layer.leaky_providers` in config.
    """
    return provider in get_leaky_providers()
