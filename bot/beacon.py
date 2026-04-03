"""Beacon background agent for Tether v3.

Two-phase design inspired by the KAIROS pattern in claude-code:
  Phase 1 — Triage: cheap Haiku call (~200 tokens), YES/NO decision
  Phase 2 — Action: Haiku with tools, max 3 conservative actions

Two trigger paths:
  1. Anchor transition — always runs (natural checkpoint, bypasses score)
  2. Bulk changes — score >= threshold between anchors (default 15,
     roughly 5+ meaningful edits)

Cooldown prevents Beacon from firing too often even when both triggers
overlap.
"""
import logging
import sqlite3
from datetime import datetime, timedelta

from bot.state_monitor import get_pending_score, is_window_settled

logger = logging.getLogger(__name__)

_MAX_BEACON_ACTIONS = 3
_DEFAULT_SCORE_THRESHOLD = 15  # ~5 task completions or ~3 tasks + context updates


# ---------------------------------------------------------------------------
# Beacon state — cooldown tracking
# ---------------------------------------------------------------------------

def record_beacon_invocation(db_path: str) -> None:
    """Record the current time as the last Beacon invocation."""
    conn = sqlite3.connect(db_path)
    try:
        now = datetime.utcnow().isoformat()
        conn.execute("UPDATE beacon_state SET last_invoked_at = ? WHERE id = 1", (now,))
        conn.commit()
    finally:
        conn.close()


def _get_last_invocation(db_path: str) -> datetime | None:
    conn = sqlite3.connect(db_path)
    try:
        row = conn.execute(
            "SELECT last_invoked_at FROM beacon_state WHERE id = 1"
        ).fetchone()
        if row and row[0]:
            return datetime.fromisoformat(row[0])
        return None
    finally:
        conn.close()


def should_trigger_beacon(
    db_path: str,
    score_threshold: int = _DEFAULT_SCORE_THRESHOLD,
    cooldown_minutes: int = 30,
    is_anchor_transition: bool = False,
) -> bool:
    """Return True if Beacon should run.

    Two trigger paths:
      1. Anchor transition — bypasses score threshold, only checks cooldown
      2. Bulk changes — debounce window must be settled AND score >= threshold

    Both paths respect the cooldown to prevent rapid re-firing.
    """
    # Cooldown check applies to both paths
    last = _get_last_invocation(db_path)
    if last is not None:
        elapsed = datetime.utcnow() - last
        if elapsed < timedelta(minutes=cooldown_minutes):
            return False

    # Path 1: anchor transition always triggers (if past cooldown)
    if is_anchor_transition:
        # Only if there are any pending changes worth reviewing
        return get_pending_score(db_path, debounce_minutes=0) > 0

    # Path 2: bulk changes — window must be settled and score must hit threshold
    if not is_window_settled(db_path):
        return False

    score = get_pending_score(db_path)
    return score >= score_threshold


# ---------------------------------------------------------------------------
# run_beacon — two-phase agent
# ---------------------------------------------------------------------------

async def run_beacon(
    router,
    db_path: str,
    changes: list[dict],
    model: str = "claude-haiku-4-5-20251001",
    tools: list | None = None,
    tool_executor=None,
) -> dict:
    """Run the two-phase Beacon agent.

    Returns a dict with keys:
      triggered: bool — whether Phase 2 ran
      message: str | None — any message to send to the user
    """
    try:
        from bot.relationships import build_beacon_context

        # Enrich change list with milestone/context relationships
        enriched_context = build_beacon_context(db_path, changes)

        # --- Phase 1: Triage ---
        triage_prompt = (
            f"The following activity was detected in the user's task system:\n\n"
            f"{enriched_context}\n\n"
            f"Does this warrant closer review and possible action? "
            f"Answer YES or NO and one sentence why."
        )
        triage_response = await router.complete(
            messages=[{"role": "user", "content": triage_prompt}],
            system="You are a background monitoring assistant. Be conservative.",
            model=model,
            thinking=False,
        )

        triage_text = triage_response.content.strip()
        if not triage_text.upper().startswith("YES"):
            return {"triggered": False, "message": None}

        # --- Phase 2: Investigation + action ---
        record_beacon_invocation(db_path)

        action_system = (
            "You are a quiet background assistant reviewing the user's task system. "
            "Take conservative, targeted action only when clearly needed. "
            "Do not send messages unless something genuinely needs the user's attention. "
            f"Limit yourself to at most {_MAX_BEACON_ACTIONS} actions."
        )
        action_prompt = (
            f"Activity detected:\n\n{enriched_context}\n\n"
            f"Review the current state and take action if needed. "
            f"You can update context entries to reflect completed work, "
            f"adjust milestone status, or flag stale information. "
            f"If nothing needs doing, say so briefly."
        )

        if tools and tool_executor:
            from bot.conversation import conversation_loop
            action_response = await conversation_loop(
                backend=router.active_backend,
                messages=[{"role": "user", "content": action_prompt}],
                system=action_system,
                model=model,
                tools=tools,
                tool_executor=tool_executor,
                max_rounds=_MAX_BEACON_ACTIONS + 1,
                thinking=False,
            )
        else:
            action_response = await router.complete(
                messages=[{"role": "user", "content": action_prompt}],
                system=action_system,
                model=model,
                thinking=False,
            )

        message = action_response.content.strip() or None
        return {"triggered": True, "message": message}

    except Exception as e:
        logger.warning("run_beacon failed: %s", e)
        return {"triggered": False, "message": None}


def _format_change_summary(changes: list[dict]) -> str:
    if not changes:
        return "No specific changes recorded."
    lines = []
    for c in changes:
        ct = c.get("change_type", "change")
        eid = c.get("entity_id", "")
        score = c.get("score", "?")
        lines.append(f"  - [{ct}] {eid} (weight: {score})")
    return "\n".join(lines)
