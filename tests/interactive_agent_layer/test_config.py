"""Tests for interactive_agent_layer.config helpers."""
from __future__ import annotations

from interactive_agent_layer import config as layer_config


def test_get_scope_radius_default(monkeypatch):
    """Defaults to a sane radius when agent_layer.scope_radius is unset."""
    monkeypatch.setattr(
        "interactive_agent_layer.config.config.get",
        lambda key, default=None: default,
    )
    assert layer_config.get_scope_radius() == 3


def test_get_scope_radius_from_config(monkeypatch):
    """Reads agent_layer.scope_radius from config when set."""
    def fake_get(key, default=None):
        if key == "agent_layer.scope_radius":
            return 5
        return default

    monkeypatch.setattr("interactive_agent_layer.config.config.get", fake_get)
    assert layer_config.get_scope_radius() == 5
