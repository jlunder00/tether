"""Regression tests — HomeDirPool.initialize() runtime template seeding.

Scenario: /home/tether/.claude.json holds OAuth credentials injected by
`claude setup-token`.  The home-dir template (/etc/claude-home-template)
is baked into the image without credentials (they're Fly secrets, not
image layers).  initialize() must seed the template .claude.json from the
running user's home dir so every warm subprocess inherits valid credentials.

Three cases:
  1. Source present, template missing  → seed (copy occurs)
  2. Source present, template present  → do NOT overwrite (idempotent)
  3. Source absent, template missing   → skip gracefully (no crash)
"""
from __future__ import annotations

import json
import tempfile
from pathlib import Path

import pytest

import agent_pool_manager.homes as homes_module
from agent_pool_manager.config import AgentPoolConfig
from agent_pool_manager.homes import HomeDirPool


# ---------------------------------------------------------------------------
# Helper
# ---------------------------------------------------------------------------

def _make_pool(base: str, template: str) -> HomeDirPool:
    cfg = AgentPoolConfig(
        capacity_total=2,
        max_age_seconds=600,
        target_depth_per_hash=1,
        prime_timeout_seconds=5,
        acquire_default_timeout=1,
        home_dir_base=base,
        home_dir_template=template,
    )
    return HomeDirPool(cfg)


# ---------------------------------------------------------------------------
# Test 1 — copies .claude.json when template is missing it
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_initialize_seeds_claude_json_into_template(monkeypatch, tmp_path):
    """initialize() copies /home/tether/.claude.json to template when absent."""
    # Fake source home dir — has .claude.json with credentials
    source_home = tmp_path / "tether-home"
    source_home.mkdir()
    source_claude_json = source_home / ".claude.json"
    source_claude_json.write_text(json.dumps({"oauthToken": "sk-ant-test-123"}))

    # Template dir exists but does NOT have .claude.json yet
    template_dir = tmp_path / "template"
    template_dir.mkdir()

    # Base dir for home dirs
    base_dir = tmp_path / "homes"
    base_dir.mkdir()

    monkeypatch.setattr(homes_module, "_AUTH_SOURCE_PATH", source_claude_json)

    pool = _make_pool(str(base_dir), str(template_dir))
    await pool.initialize()

    seeded = template_dir / ".claude.json"
    assert seeded.exists(), "initialize() must copy .claude.json into the template dir"
    assert json.loads(seeded.read_text())["oauthToken"] == "sk-ant-test-123"


# ---------------------------------------------------------------------------
# Test 2 — does NOT overwrite existing template .claude.json
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_initialize_does_not_overwrite_existing_template_claude_json(monkeypatch, tmp_path):
    """initialize() must not overwrite template .claude.json if it already exists."""
    source_home = tmp_path / "tether-home"
    source_home.mkdir()
    source_claude_json = source_home / ".claude.json"
    source_claude_json.write_text(json.dumps({"oauthToken": "new-token"}))

    template_dir = tmp_path / "template"
    template_dir.mkdir()
    existing = template_dir / ".claude.json"
    existing.write_text(json.dumps({"oauthToken": "original-token"}))

    base_dir = tmp_path / "homes"
    base_dir.mkdir()

    monkeypatch.setattr(homes_module, "_AUTH_SOURCE_PATH", source_claude_json)

    pool = _make_pool(str(base_dir), str(template_dir))
    await pool.initialize()

    preserved = json.loads((template_dir / ".claude.json").read_text())
    assert preserved["oauthToken"] == "original-token", (
        "initialize() must not overwrite template .claude.json that already exists"
    )


# ---------------------------------------------------------------------------
# Test 3 — handles missing source gracefully (no crash)
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_initialize_skips_seeding_when_source_missing(monkeypatch, tmp_path):
    """initialize() does not crash when /home/tether/.claude.json doesn't exist."""
    # Source path points to a nonexistent file
    source_home = tmp_path / "tether-home"
    source_home.mkdir()
    missing_source = source_home / ".claude.json"  # NOT created

    template_dir = tmp_path / "template"
    template_dir.mkdir()

    base_dir = tmp_path / "homes"
    base_dir.mkdir()

    monkeypatch.setattr(homes_module, "_AUTH_SOURCE_PATH", missing_source)

    pool = _make_pool(str(base_dir), str(template_dir))
    # Must not raise
    await pool.initialize()

    assert not (template_dir / ".claude.json").exists(), (
        "initialize() must not create template .claude.json when source is absent"
    )
    # Pool is still usable
    assert pool.available_count() == 2
