"""DB state change monitor for the Beacon background agent.

Records weighted change events to state_monitor_log. The Beacon
polls get_pending_score() and triggers when the threshold is met.
Changes are marked consumed after each Beacon invocation so scores
don't compound across runs.
"""
import logging
import sqlite3
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


def record_change(db_path: str, change_type: str, entity_id: str) -> None:
    """Record a state change with its weighted score."""
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


def get_pending_score(db_path: str) -> int:
    """Sum of scores for all unconsumed change events."""
    conn = sqlite3.connect(db_path)
    try:
        row = conn.execute(
            "SELECT COALESCE(SUM(score), 0) FROM state_monitor_log WHERE consumed = 0"
        ).fetchone()
        return int(row[0])
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
