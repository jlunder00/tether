"""Beacon background agent for Tether v3.

Two-phase design inspired by the KAIROS pattern in claude-code:
  Phase 1 — Triage: cheap Haiku call (~200 tokens), YES/NO decision
  Phase 2 — Action: Haiku with tools, max 3 conservative actions

Beacon is triggered by the state_monitor's weighted scoring ledger,
not by a time ticker. This keeps LLM costs proportional to real
activity rather than wall-clock time.
"""
import logging
import sqlite3
from datetime import datetime, timedelta

from bot.state_monitor import get_pending_score

logger = logging.getLogger(__name__)

_MAX_BEACON_ACTIONS = 3


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
    score_threshold: int = 8,
    cooldown_minutes: int = 30,
) -> bool:
    """Return True if accumulated score >= threshold AND cooldown has passed."""
    score = get_pending_score(db_path)
    if score < score_threshold:
        return False

    last = _get_last_invocation(db_path)
    if last is None:
        return True
    elapsed = datetime.utcnow() - last
    return elapsed >= timedelta(minutes=cooldown_minutes)


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
        change_summary = _format_change_summary(changes)

        # --- Phase 1: Triage ---
        triage_prompt = (
            f"These changes were detected in the user's task system:\n{change_summary}\n\n"
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
            f"Changes detected:\n{change_summary}\n\n"
            f"Review the current state and take action if needed. "
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
