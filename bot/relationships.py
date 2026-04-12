"""Relationship resolver for the Beacon agent.

Traces links between tasks, milestones, and context entries so the Beacon
can make relationship-aware decisions. Two link paths:

  1. Direct: tasks.context_subject column (single context per task)
  2. Indirect: milestone_tasks → milestones → context_subject

When a task changes, we trace both paths to determine which context entries
are affected and should be reviewed.
"""
import logging
import sqlite3
from collections import defaultdict
from pathlib import Path

from db.queries import get_milestones

logger = logging.getLogger(__name__)


def resolve_task_context(db_path: str, task_id: str) -> list[dict]:
    """Given a task UUID, find all context entries linked to it.

    Two link paths:
      1. Direct: tasks.context_subject column (single context per task)
      2. Indirect: milestone_tasks → milestones → context_subject

    Returns a list of dicts with keys:
        context_subject, source ("direct" | "milestone"),
        milestone_id, milestone_name, milestone_status, task_count, done_count
        (milestone fields are None for direct links)
    """
    results = []
    seen_subjects = set()

    # --- Path 1: direct context_subject on task ---
    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    try:
        row = conn.execute(
            "SELECT context_subject FROM tasks WHERE uuid = ?",
            (task_id,),
        ).fetchone()
        if row and row["context_subject"]:
            subj = row["context_subject"]
            seen_subjects.add(subj)
            results.append({
                "context_subject": subj,
                "source": "direct",
                "milestone_id": None,
                "milestone_name": None,
                "milestone_status": None,
                "task_count": None,
                "done_count": None,
            })

        # --- Path 2: via milestones ---
        milestone_rows = conn.execute(
            "SELECT milestone_id FROM milestone_tasks WHERE task_id = ?",
            (task_id,),
        ).fetchall()
        milestone_ids = [r["milestone_id"] for r in milestone_rows]
    finally:
        conn.close()

    if milestone_ids:
        all_milestones = get_milestones(db_path)
        for m in all_milestones:
            if m["id"] in milestone_ids:
                # Always include milestone links — they carry progress info
                # even if the same subject is already linked directly
                results.append({
                    "context_subject": m["context_subject"],
                    "source": "milestone",
                    "milestone_id": m["id"],
                    "milestone_name": m["name"],
                    "milestone_status": m["status"],
                    "task_count": m["task_count"],
                    "done_count": m["done_count"],
                })

    return results


def get_milestone_summary(db_path: str, milestone_id: str) -> dict | None:
    """Get enriched milestone info including completion ratio."""
    all_milestones = get_milestones(db_path)
    m = next((m for m in all_milestones if m["id"] == milestone_id), None)
    if m is None:
        return None
    total = m["task_count"]
    done = m["done_count"]
    return {
        "id": m["id"],
        "name": m["name"],
        "context_subject": m["context_subject"],
        "status": m["status"],
        "task_count": total,
        "done_count": done,
        "completion": done / total if total > 0 else 0.0,
        "target_date": m["target_date"],
        "tasks": m.get("tasks", []),
    }


def get_affected_context_subjects(db_path: str, changes: list[dict]) -> list[str]:
    """Given a list of change events, return deduplicated context subjects affected.

    Handles:
    - task_done / task_blocked / task_created → trace via direct task_context + milestone links
    - context_updated → the subject itself
    - plan_restructured → all milestones' context subjects
    """
    subjects = set()

    task_change_types = {"task_done", "task_blocked", "task_created"}

    for change in changes:
        ct = change.get("change_type", "")
        eid = change.get("entity_id", "")

        if ct in task_change_types:
            links = resolve_task_context(db_path, eid)
            for link in links:
                subjects.add(link["context_subject"])

        elif ct == "context_updated":
            subjects.add(eid)

        elif ct == "plan_restructured":
            # All milestones could be affected
            milestones = get_milestones(db_path)
            for m in milestones:
                subjects.add(m["context_subject"])

    return sorted(subjects)


def build_beacon_context(db_path: str, changes: list[dict]) -> str:
    """Build an enriched context string for the Beacon triage prompt.

    Includes: change summary, affected context subjects, milestone status
    for any milestones linked to changed tasks.
    """
    if not changes:
        return "No specific changes recorded."

    sections = []

    # Change summary
    change_lines = []
    for c in changes:
        ct = c.get("change_type", "change")
        eid = c.get("entity_id", "")
        score = c.get("score", "?")
        change_lines.append(f"  - [{ct}] {eid} (weight: {score})")
    sections.append("Changes:\n" + "\n".join(change_lines))

    # Affected context subjects
    affected = get_affected_context_subjects(db_path, changes)
    if affected:
        sections.append("Affected context entries:\n" +
                         "\n".join(f"  - {s}" for s in affected))

    # Relationship details for affected tasks
    seen_milestones = set()
    task_change_types = {"task_done", "task_blocked", "task_created"}
    for change in changes:
        if change.get("change_type") in task_change_types:
            links = resolve_task_context(db_path, change.get("entity_id", ""))
            for link in links:
                if link["source"] == "direct":
                    sections.append(
                        f"Direct link: task → context: {link['context_subject']}"
                    )
                elif link["milestone_id"] and link["milestone_id"] not in seen_milestones:
                    seen_milestones.add(link["milestone_id"])
                    summary = get_milestone_summary(db_path, link["milestone_id"])
                    if summary:
                        pct = int(summary["completion"] * 100)
                        sections.append(
                            f"Milestone: {summary['name']} "
                            f"({summary['done_count']}/{summary['task_count']} tasks, {pct}% complete) "
                            f"→ context: {summary['context_subject']}"
                        )

    return "\n\n".join(sections)
