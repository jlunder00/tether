"""Pool warm endpoint — user-facing hint to pre-warm a subprocess for the caller.

POST /api/internal/pool/warm
  Auth: cookie JWT (user-session auth, NOT X-Internal-Token cron auth)
  Body: { "agent_version": str }
  Response: 202 { "hinted": bool, "options_hash": str }

Always returns 202 — warming is best-effort and must never block the frontend.
Pool failure is logged and reflected in hinted=false for observability.
"""
from __future__ import annotations

import hashlib
import json
import logging
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel

from api.auth import auth_dependency

log = logging.getLogger(__name__)

router = APIRouter()

# ---------------------------------------------------------------------------
# Canonical options per agent version.
#
# These MUST match what bot.agent_dispatch passes to the layer on session/start.
# If _V2_0_OPTIONS changes in agent_dispatch, update this mapping too — and
# the test test_warm_options_hash_matches_layer_algorithm will catch any drift.
# ---------------------------------------------------------------------------

def _get_agent_options() -> dict[str, dict[str, Any]]:
    """Lazy import so agent_dispatch doesn't load at module import time."""
    try:
        from bot.agent_dispatch import _V2_0_OPTIONS
        v2_options: dict[str, Any] = _V2_0_OPTIONS
    except ImportError:
        v2_options = {}

    return {
        "tether-agent-1.0": {},
        "tether-agent-2.0": v2_options,
        # 2.5 goes through the premium handler directly (not the layer),
        # so pool warming via layer is not applicable. We still accept 2.5
        # and warm with a minimal options set so the FE can fire unconditionally.
        "tether-agent-2.5": v2_options,
    }


def _compute_options_hash(options: dict[str, Any]) -> str:
    """SHA-256 canonical-JSON hash, truncated to 16 hex chars.

    Algorithm is identical to interactive_agent_layer.session._stable_options_hash.
    Both must stay in sync — the test test_warm_options_hash_matches_layer_algorithm
    enforces this.
    """
    canonical = json.dumps(options, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(canonical.encode()).hexdigest()[:16]


def _get_pool_client(request: Request):
    """Return the pool client, lazily constructing and caching on app.state.

    Tests inject a mock by setting ``app.state.pool_client`` before requests.
    In production the client is constructed once from config and reused, so
    httpx connection pooling applies across requests.
    """
    client = getattr(request.app.state, "pool_client", None)
    if client is not None:
        return client

    # Construct from config on first use and cache for the app's lifetime.
    try:
        from config.loader import config
        base_url: str = config.get("agent_pool.base_url", "http://127.0.0.1:5002")
    except Exception:
        base_url = "http://127.0.0.1:5002"

    from agent_pool_manager.client import PoolClient
    pool_client = PoolClient(base_url=base_url)
    request.app.state.pool_client = pool_client
    return pool_client


# ---------------------------------------------------------------------------
# Request / response models
# ---------------------------------------------------------------------------

class WarmRequest(BaseModel):
    agent_version: str


# ---------------------------------------------------------------------------
# Endpoint
# ---------------------------------------------------------------------------

@router.post("/warm", status_code=202)
async def pool_warm(
    body: WarmRequest,
    request: Request,
    _auth: dict = Depends(auth_dependency),
) -> dict:
    """Pre-warm a pool subprocess for the authenticated user.

    Returns 202 always — warming is best-effort.  ``hinted=false`` signals
    that the pool call failed (pool unreachable), but the FE should not retry
    aggressively; the next real acquire will fall through to cold-start.
    """
    user_id: str = request.state.user_id

    agent_options = _get_agent_options()
    options = agent_options.get(body.agent_version)
    if options is None:
        raise HTTPException(
            status_code=400,
            detail=f"Unknown agent_version: {body.agent_version!r}. "
                   f"Valid versions: {sorted(agent_options)}",
        )

    options_hash = _compute_options_hash(options)
    pool_client = _get_pool_client(request)

    hinted = False
    try:
        await pool_client.hint(user_id, options_hash, options)
        hinted = True
    except Exception as exc:
        log.warning(
            "pool_warm: pool hint failed user_id=%s agent_version=%s: %s",
            user_id,
            body.agent_version,
            exc,
        )

    return {"hinted": hinted, "options_hash": options_hash}
