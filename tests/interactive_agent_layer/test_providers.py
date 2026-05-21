"""Unit tests for interactive_agent_layer.providers.

Tests cover:
- get_user_provider stub returns 'anthropic_oauth' for any user_id
- is_leaky_provider returns True for providers in the leaky_providers config list
- is_leaky_provider returns False for safe providers (anthropic_oauth, etc.)
"""
from __future__ import annotations

from unittest.mock import patch


# ---------------------------------------------------------------------------
# get_user_provider stub
# ---------------------------------------------------------------------------

def test_get_user_provider_returns_anthropic_oauth():
    """Stub must return 'anthropic_oauth' for any user_id."""
    from interactive_agent_layer.providers import get_user_provider

    assert get_user_provider("user-abc") == "anthropic_oauth"
    assert get_user_provider("user-xyz") == "anthropic_oauth"
    assert get_user_provider("") == "anthropic_oauth"


# ---------------------------------------------------------------------------
# is_leaky_provider
# ---------------------------------------------------------------------------

def test_is_leaky_provider_true_for_openrouter():
    """openrouter is in the default leaky_providers list."""
    with patch(
        "interactive_agent_layer.providers.get_leaky_providers",
        return_value=["openrouter", "openai"],
    ):
        from interactive_agent_layer.providers import is_leaky_provider
        assert is_leaky_provider("openrouter") is True


def test_is_leaky_provider_true_for_openai():
    """openai is in the default leaky_providers list."""
    with patch(
        "interactive_agent_layer.providers.get_leaky_providers",
        return_value=["openrouter", "openai"],
    ):
        from interactive_agent_layer.providers import is_leaky_provider
        assert is_leaky_provider("openai") is True


def test_is_leaky_provider_false_for_anthropic_oauth():
    """anthropic_oauth is safe — not in leaky_providers."""
    with patch(
        "interactive_agent_layer.providers.get_leaky_providers",
        return_value=["openrouter", "openai"],
    ):
        from interactive_agent_layer.providers import is_leaky_provider
        assert is_leaky_provider("anthropic_oauth") is False


def test_is_leaky_provider_false_for_unknown_provider():
    """Providers not in the list are treated as safe (not leaky)."""
    with patch(
        "interactive_agent_layer.providers.get_leaky_providers",
        return_value=["openrouter", "openai"],
    ):
        from interactive_agent_layer.providers import is_leaky_provider
        assert is_leaky_provider("some_new_provider") is False
