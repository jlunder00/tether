"""Two-envelope scope model: PermissionGate and injection-cascade envelopes.

Both envelopes share one geometry `(radius, m_max, decay)` under the top-level
`scope:` config namespace (config-namespace-decision-2026-07-04.md):

    scope:
      permission:   # PermissionGate envelope — readable WITHOUT a permission card
        radius: 3
        m_max: 4
        decay: 1
      injection:    # session-start cascade envelope — auto-injected content
        radius: 1
        m_max: 2
        decay: 0
      scenarios: {}  # per-scenario partial overrides, e.g. scenarios.<name>.permission

`load_injection_envelope()` always validates the injection envelope is a
subset of the permission envelope for the same scenario (`validate_injection_subset`)
and raises `ScopeConfigError` at load time on violation — fail fast, no clamping.
"""
from __future__ import annotations

from dataclasses import dataclass

from config.loader import config

# Defaults preserve today's behavior: permission 3/4/1 matches the existing
# agent_layer.scope_radius default (3) with the D04 4/3/2/1 ring curve;
# injection 1/2/0 matches the current flat cascade (depth 1, M=2).
_PERMISSION_DEFAULT = {"radius": 3, "m_max": 4, "decay": 1}
_INJECTION_DEFAULT = {"radius": 1, "m_max": 2, "decay": 0}


class ScopeConfigError(Exception):
    """Raised when the injection envelope is not a subset of the permission
    envelope for the same scenario — fail fast at config-load time."""


@dataclass(frozen=True)
class ScopeEnvelope:
    """A graded scope geometry: how far (radius) and how much detail
    (m_max, decayed per hop) is allowed at each tree distance."""

    radius: int
    m_max: int
    decay: int

    def m_allowed(self, d: int) -> int | None:
        """Detail tier allowed at tree distance *d*, or None if *d* is out of
        scope entirely (d > radius). Clamped to a minimum of 1 within radius."""
        if d > self.radius:
            return None
        return max(1, self.m_max - self.decay * d)


def _merge_scenario(base: dict, scenario: str | None, subkey: str) -> dict:
    """Partial-merge a per-scenario override onto the base envelope dict."""
    if scenario is None:
        return base
    override = config.get(f"scope.scenarios.{scenario}.{subkey}", {}) or {}
    return {**base, **override}


def load_permission_envelope(scenario: str | None = None) -> ScopeEnvelope:
    """Load the PermissionGate envelope from `scope.permission`, with an
    optional per-scenario partial override from `scope.scenarios.<name>.permission`."""
    base = config.get("scope.permission", _PERMISSION_DEFAULT) or _PERMISSION_DEFAULT
    merged = _merge_scenario(base, scenario, "permission")
    return ScopeEnvelope(**merged)


def load_injection_envelope(scenario: str | None = None) -> ScopeEnvelope:
    """Load the injection-cascade envelope from `scope.injection`, with an
    optional per-scenario partial override from `scope.scenarios.<name>.injection`.

    Validates the loaded envelope is a subset of the same-scenario permission
    envelope on every call — raises ScopeConfigError on violation.
    """
    base = config.get("scope.injection", _INJECTION_DEFAULT) or _INJECTION_DEFAULT
    merged = _merge_scenario(base, scenario, "injection")
    injection = ScopeEnvelope(**merged)
    permission = load_permission_envelope(scenario)
    validate_injection_subset(injection, permission)
    return injection


def validate_injection_subset(inj: ScopeEnvelope, perm: ScopeEnvelope) -> None:
    """Enforce `injection ⊆ permission`: inj.radius <= perm.radius AND
    inj.m_allowed(d) <= perm.m_allowed(d) for every d in [0, inj.radius].

    The full loop is required, not just endpoints — two clamped-linear curves
    can cross mid-range. Raises ScopeConfigError naming both envelopes on
    the first violating distance found.
    """
    if inj.radius > perm.radius:
        raise ScopeConfigError(
            f"injection envelope radius ({inj.radius}) exceeds permission "
            f"envelope radius ({perm.radius}) — injection must be a subset "
            f"of permission (scope.injection vs scope.permission)"
        )
    for d in range(0, inj.radius + 1):
        inj_m = inj.m_allowed(d)
        perm_m = perm.m_allowed(d)
        if inj_m is not None and (perm_m is None or inj_m > perm_m):
            raise ScopeConfigError(
                f"injection envelope allows more detail than permission "
                f"envelope at distance {d} (injection m_allowed={inj_m}, "
                f"permission m_allowed={perm_m}) — injection must be a "
                f"subset of permission (scope.injection vs scope.permission)"
            )
