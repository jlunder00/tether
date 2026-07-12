"""Tests for interactive_agent_layer.config helpers."""
from __future__ import annotations

from interactive_agent_layer import config as layer_config


def test_get_permission_timeout_default(monkeypatch):
    """Defaults to 120s when agent_layer.permission_timeout_seconds is unset.

    get_scope_radius() was deleted (replaced by envelope.load_permission_envelope());
    scope radius now lives in the ScopeEnvelope, not a bare config int.
    """
    monkeypatch.setattr(
        "interactive_agent_layer.config.config.get",
        lambda key, default=None: default,
    )
    assert layer_config.get_permission_timeout() == 120


def test_get_permission_timeout_from_config(monkeypatch):
    """Reads agent_layer.permission_timeout_seconds from config when set."""
    def fake_get(key, default=None):
        if key == "agent_layer.permission_timeout_seconds":
            return 45
        return default

    monkeypatch.setattr("interactive_agent_layer.config.config.get", fake_get)
    assert layer_config.get_permission_timeout() == 45


def test_get_scope_radius_removed():
    """get_scope_radius() is deleted — replaced by envelope.load_permission_envelope()."""
    assert not hasattr(layer_config, "get_scope_radius")
