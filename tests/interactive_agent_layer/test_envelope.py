"""Tests for interactive_agent_layer.envelope — ScopeEnvelope + loaders + ⊆ validator."""
from __future__ import annotations

import pathlib

import pytest
import yaml

from interactive_agent_layer.envelope import (
    ScopeEnvelope,
    ScopeConfigError,
    load_injection_envelope,
    load_permission_envelope,
    validate_injection_subset,
)


def _load_committed_app_config() -> dict:
    """Load the committed config/app_config.yaml (not user overrides)."""
    base = pathlib.Path(__file__).resolve()
    for parent in base.parents:
        candidate = parent / "config" / "app_config.yaml"
        if candidate.exists():
            with open(candidate) as f:
                return yaml.safe_load(f)
    raise FileNotFoundError("config/app_config.yaml not found from test location")


# ---------------------------------------------------------------------------
# ScopeEnvelope.m_allowed
# ---------------------------------------------------------------------------

def test_m_allowed_beyond_radius_is_none():
    env = ScopeEnvelope(radius=3, m_max=4, decay=1)
    assert env.m_allowed(4) is None


def test_m_allowed_at_radius_boundary():
    env = ScopeEnvelope(radius=3, m_max=4, decay=1)
    assert env.m_allowed(3) == 1


def test_m_allowed_at_zero_distance_is_m_max():
    env = ScopeEnvelope(radius=3, m_max=4, decay=1)
    assert env.m_allowed(0) == 4


def test_m_allowed_clamped_to_one_minimum():
    """decay*d can exceed m_max — result must never drop below 1 within radius."""
    env = ScopeEnvelope(radius=5, m_max=4, decay=3)
    assert env.m_allowed(2) == 1  # 4 - 3*2 = -2, clamped to 1


def test_m_allowed_flat_curve_when_decay_zero():
    env = ScopeEnvelope(radius=1, m_max=2, decay=0)
    assert env.m_allowed(0) == 2
    assert env.m_allowed(1) == 2


def test_envelope_is_frozen():
    env = ScopeEnvelope(radius=3, m_max=4, decay=1)
    with pytest.raises(Exception):
        env.radius = 10  # type: ignore[misc]


# ---------------------------------------------------------------------------
# validate_injection_subset — the ⊆ rule, including mid-range crossing
# ---------------------------------------------------------------------------

def test_validate_injection_subset_passes_for_current_defaults():
    perm = ScopeEnvelope(radius=3, m_max=4, decay=1)
    inj = ScopeEnvelope(radius=1, m_max=2, decay=0)
    # Must not raise.
    validate_injection_subset(inj, perm)


def test_validate_injection_subset_radius_violation():
    perm = ScopeEnvelope(radius=2, m_max=4, decay=1)
    inj = ScopeEnvelope(radius=3, m_max=2, decay=0)
    with pytest.raises(ScopeConfigError):
        validate_injection_subset(inj, perm)


def test_validate_injection_subset_endpoint_only_check_is_insufficient():
    """Regression guard: curves that agree at d=0 and at inj.radius can still
    cross in between. The validator must walk every d in [0, inj.radius], not
    just the endpoints.

    perm: radius=5, m_max=4, decay=3 -> [4, 1, 1, 1, 1, 1]
    inj:  radius=4, m_max=3, decay=1 -> [3, 2, 1, 1, 1]

    Endpoints (d=0: 3<=4, d=4: 1<=1) both pass, but d=1 (inj=2 > perm=1) fails.
    """
    perm = ScopeEnvelope(radius=5, m_max=4, decay=3)
    inj = ScopeEnvelope(radius=4, m_max=3, decay=1)
    with pytest.raises(ScopeConfigError):
        validate_injection_subset(inj, perm)


def test_validate_injection_subset_error_names_both_keys():
    perm = ScopeEnvelope(radius=5, m_max=4, decay=3)
    inj = ScopeEnvelope(radius=4, m_max=3, decay=1)
    with pytest.raises(ScopeConfigError, match="permission"):
        validate_injection_subset(inj, perm)


# ---------------------------------------------------------------------------
# load_permission_envelope / load_injection_envelope
# ---------------------------------------------------------------------------

def test_load_permission_envelope_defaults(monkeypatch):
    monkeypatch.setattr(
        "interactive_agent_layer.envelope.config.get",
        lambda key, default=None: default,
    )
    env = load_permission_envelope()
    assert env == ScopeEnvelope(radius=3, m_max=4, decay=1)


def test_load_permission_envelope_from_config(monkeypatch):
    def fake_get(key, default=None):
        if key == "scope.permission":
            return {"radius": 5, "m_max": 4, "decay": 1}
        return default

    monkeypatch.setattr("interactive_agent_layer.envelope.config.get", fake_get)
    env = load_permission_envelope()
    assert env == ScopeEnvelope(radius=5, m_max=4, decay=1)


def test_load_permission_envelope_scenario_partial_merge(monkeypatch):
    def fake_get(key, default=None):
        if key == "scope.permission":
            return {"radius": 3, "m_max": 4, "decay": 1}
        if key == "scope.scenarios.beacon_autonomous.permission":
            return {"radius": 5, "decay": 1}
        return default

    monkeypatch.setattr("interactive_agent_layer.envelope.config.get", fake_get)
    env = load_permission_envelope(scenario="beacon_autonomous")
    # radius/decay overridden, m_max inherited from the base envelope.
    assert env == ScopeEnvelope(radius=5, m_max=4, decay=1)


def test_load_injection_envelope_defaults(monkeypatch):
    monkeypatch.setattr(
        "interactive_agent_layer.envelope.config.get",
        lambda key, default=None: default,
    )
    env = load_injection_envelope()
    assert env == ScopeEnvelope(radius=1, m_max=2, decay=0)


def test_load_injection_envelope_raises_on_subset_violation(monkeypatch):
    def fake_get(key, default=None):
        if key == "scope.permission":
            return {"radius": 5, "m_max": 4, "decay": 3}
        if key == "scope.injection":
            return {"radius": 4, "m_max": 3, "decay": 1}
        return default

    monkeypatch.setattr("interactive_agent_layer.envelope.config.get", fake_get)
    with pytest.raises(ScopeConfigError):
        load_injection_envelope()


def test_load_injection_envelope_validates_against_matching_scenario(monkeypatch):
    """A scenario override on the permission side must be honored when
    validating the injection envelope for that same scenario."""
    def fake_get(key, default=None):
        if key == "scope.permission":
            return {"radius": 5, "m_max": 4, "decay": 1}
        if key == "scope.injection":
            return {"radius": 1, "m_max": 2, "decay": 0}
        if key == "scope.scenarios.tight.permission":
            return {"radius": 0}
        if key == "scope.scenarios.tight.injection":
            return {"radius": 0}
        return default

    monkeypatch.setattr("interactive_agent_layer.envelope.config.get", fake_get)
    # Base defaults are fine (inj radius 1 <= perm radius 5).
    load_injection_envelope()
    # Scenario "tight" clamps injection radius to 0 too, still within its own
    # scenario permission radius (0) -> should not raise.
    load_injection_envelope(scenario="tight")


# ---------------------------------------------------------------------------
# The committed config/app_config.yaml scope: block
# ---------------------------------------------------------------------------

def test_committed_yaml_scope_block_matches_inert_defaults():
    cfg = _load_committed_app_config()
    scope = cfg["scope"]
    assert scope["permission"] == {"radius": 3, "m_max": 4, "decay": 1}
    assert scope["injection"] == {"radius": 1, "m_max": 2, "decay": 0}
    assert scope["scenarios"] == {}


def test_committed_yaml_scope_block_passes_subset_validation():
    cfg = _load_committed_app_config()
    perm = ScopeEnvelope(**cfg["scope"]["permission"])
    inj = ScopeEnvelope(**cfg["scope"]["injection"])
    validate_injection_subset(inj, perm)  # must not raise


def test_committed_yaml_permission_timeout_is_120():
    cfg = _load_committed_app_config()
    assert cfg["agent_layer"]["permission_timeout_seconds"] == 120
