"""DB state change monitor for the Beacon background agent.

Changes are recorded as raw events. Rather than scoring each individual
change immediately, a debounce window collects changes and scores the
batch when the window expires. This prevents the bot's own multi-step
tool calls from inflating the score.

Flow:
  1. record_change() logs raw events (no score yet)
  2. get_pending_batch() returns events in the current debounce window
  3. score_batch() evaluates the batch after the window closes —
     deduplicates by (change_type, entity_id) so 3 updates to the
     same task count as one
  4. consume_changes() marks the batch done after Beacon runs
"""
import logging
import sqlite3
from datetime import datetime, timedelta, timezone
from pathlib import Path

logger = logging.getLogger(__name__)

CHANGE_WEIGHTS: dict[str, int] = {
    "task_done":        2,
    "task_blocked":     2,
    "context_updated":  3,
    "plan_restructured": 5,
    "acknowledgement":  1,
    "task_created":     1,
}
_DEFAULT_WEIGHT = 1
DEBOUNCE_MINUTES = 10


def record_change(db_path: str, change_type: str, entity_id: str) -> None:
    """Record a raw state change event. Score is stored per-event but
    the effective score is computed at batch evaluation time with dedup."""
    score = CHANGE_WEIGHTS.get(change_type, _DEFAULT_WEIGHT)
    conn = sqlite3.connect(db_path)
    try:
        conn.execute(
            "INSERT INTO state_monitor_log (change_type, entity_id, score) VALUES (?, ?, ?)",
            (change_type, entity_id, score),
        )
        conn.commit()
    finally:
        conn.close()


def get_pending_score(db_path: str, debounce_minutes: int = DEBOUNCE_MINUTES) -> int:
    """Score of unconsumed changes, deduplicated by (change_type, entity_id).

    Only counts changes older than the debounce window — recent changes
    may still be part of an in-progress bot action.
    """
    cutoff = (datetime.now(timezone.utc) - timedelta(minutes=debounce_minutes)).strftime(
        "%Y-%m-%d %H:%M:%S"
    )
    conn = sqlite3.connect(db_path)
    try:
        # Take the MAX score per unique (change_type, entity_id) pair,
        # only for events that have settled (older than debounce window)
        row = conn.execute(
            "SELECT COALESCE(SUM(max_score), 0) FROM ("
            "  SELECT MAX(score) AS max_score"
            "  FROM state_monitor_log"
            "  WHERE consumed = 0 AND ts <= ?"
            "  GROUP BY change_type, entity_id"
            ")",
            (cutoff,),
        ).fetchone()
        return int(row[0])
    finally:
        conn.close()


def get_window_age_minutes(db_path: str) -> float | None:
    """Minutes since the oldest unconsumed change, or None if no pending changes."""
    conn = sqlite3.connect(db_path)
    try:
        row = conn.execute(
            "SELECT MIN(ts) FROM state_monitor_log WHERE consumed = 0"
        ).fetchone()
        if not row or not row[0]:
            return None
        oldest = datetime.strptime(row[0], "%Y-%m-%d %H:%M:%S")
        elapsed = datetime.utcnow() - oldest
        return elapsed.total_seconds() / 60
    finally:
        conn.close()


def is_window_settled(db_path: str, debounce_minutes: int = DEBOUNCE_MINUTES) -> bool:
    """True if there are pending changes AND the debounce window has passed
    (no changes in the last debounce_minutes)."""
    conn = sqlite3.connect(db_path)
    try:
        # Any unconsumed changes at all?
        has_pending = conn.execute(
            "SELECT 1 FROM state_monitor_log WHERE consumed = 0 LIMIT 1"
        ).fetchone()
        if not has_pending:
            return False

        # Any changes within the debounce window?
        cutoff = (datetime.now(timezone.utc) - timedelta(minutes=debounce_minutes)).strftime(
            "%Y-%m-%d %H:%M:%S"
        )
        recent = conn.execute(
            "SELECT 1 FROM state_monitor_log WHERE consumed = 0 AND ts > ? LIMIT 1",
            (cutoff,),
        ).fetchone()
        # Settled = no recent changes (all changes are older than debounce window)
        return recent is None
    finally:
        conn.close()


def consume_changes(db_path: str) -> list[dict]:
    """Mark all pending changes as consumed and return their summaries."""
    conn = sqlite3.connect(db_path)
    try:
        rows = conn.execute(
            "SELECT id, change_type, entity_id, score, ts "
            "FROM state_monitor_log WHERE consumed = 0 ORDER BY ts"
        ).fetchall()
        changes = [
            {"id": r[0], "change_type": r[1], "entity_id": r[2],
             "score": r[3], "ts": r[4]}
            for r in rows
        ]
        if changes:
            ids = [c["id"] for c in changes]
            conn.execute(
                f"UPDATE state_monitor_log SET consumed = 1 WHERE id IN ({','.join('?' * len(ids))})",
                ids,
            )
            conn.commit()
        return changes
    finally:
        conn.close()
