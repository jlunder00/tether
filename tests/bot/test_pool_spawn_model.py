"""Regression test: pool spawn options must use the full Anthropic API model ID.

`haiku-4.5` and `claude-haiku-4-5` are shorthand names that the Anthropic API
does NOT recognise — they return 404.  The correct ID is `claude-haiku-4-5-20251001`.

These tests guard both fix sites:
  1. bot.agent_dispatch._V2_0_OPTIONS["model"]   — controls what the pool warms
  2. config/app_config.yaml models.* entries      — controls non-pool pipeline calls
"""
from __future__ import annotations

import os

import pytest
import yaml

os.environ.setdefault("TETHER_JWT_SECRET", "test-secret-for-tests")

CORRECT_HAIKU_MODEL = "claude-haiku-4-5-20251001"

# ---------------------------------------------------------------------------
# Fix site 1: agent_dispatch._V2_0_OPTIONS
# ---------------------------------------------------------------------------

def test_v2_0_options_uses_full_model_id():
    """_V2_0_OPTIONS must use the full Anthropic API model ID for haiku."""
    from bot.agent_dispatch import _V2_0_OPTIONS

    model = _V2_0_OPTIONS.get("model")
    assert model == CORRECT_HAIKU_MODEL, (
        f"_V2_0_OPTIONS['model'] = {model!r}. "
        f"Expected full API model ID {CORRECT_HAIKU_MODEL!r}. "
        "Short names like 'haiku-4.5' return 404 from the Anthropic API, "
        "causing every pool-warmed subprocess query to fail."
    )


# ---------------------------------------------------------------------------
# Fix site 2: app_config.yaml models section
# ---------------------------------------------------------------------------

def _load_app_config() -> dict:
    """Load the committed app_config.yaml (not user overrides)."""
    from pathlib import Path
    # Walk up from tests/bot/ to find config/app_config.yaml
    base = Path(__file__).parent.parent.parent  # repo root
    config_path = base / "config" / "app_config.yaml"
    with open(config_path) as f:
        return yaml.safe_load(f)


@pytest.mark.parametrize("role", ["meta_eval", "quick_classifier", "satisfaction_eval"])
def test_app_config_haiku_roles_use_full_model_id(role: str):
    """app_config.yaml haiku model roles must use the full Anthropic API model ID."""
    cfg = _load_app_config()
    models = cfg.get("models", {})
    model = models.get(role)
    assert model == CORRECT_HAIKU_MODEL, (
        f"config/app_config.yaml models.{role} = {model!r}. "
        f"Expected {CORRECT_HAIKU_MODEL!r}. "
        "Short form 'claude-haiku-4-5' is not a valid Anthropic API model ID."
    )
