"""Memory management for Tether v3.

Three layers:
1. Session notes — short-lived file injected into the system prompt,
   updated by a Haiku call at meaningful moments (fire-and-forget).
2. Event-driven commits — at anchor transitions and after significant
   mutations, summaries are appended to context_entries in the DB.
3. Emergency compaction — only when conversation exceeds 90% of the
   context limit; compresses history into a synthetic summary message.
"""
import asyncio
import logging
from pathlib import Path

logger = logging.getLogger(__name__)

# Approximate chars-per-token ratio for rough context estimation
_CHARS_PER_TOKEN = 4
_COMPACT_THRESHOLD = 0.90
_SIGNIFICANT_MUTATION_THRESHOLD = 3

_SESSION_NOTES_TEMPLATE = """# Session Notes

## Current State
<!-- What's happening right now -->

## Today's Progress
<!-- What got done this session -->

## Active Context
<!-- Key context entries referenced, their current state -->

## Recent Decisions
<!-- Choices made and why -->

## Open Items
<!-- Things mentioned but not yet handled -->
"""


# ---------------------------------------------------------------------------
# Session notes — file I/O
# ---------------------------------------------------------------------------

def read_session_notes(notes_path: str) -> str | None:
    """Read session notes from file. Returns None if missing or empty."""
    try:
        content = Path(notes_path).read_text()
        return content if content.strip() else None
    except FileNotFoundError:
        return None


def write_session_notes(content: str, notes_path: str) -> None:
    """Write session notes, creating parent directories as needed."""
    p = Path(notes_path)
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(content)


# ---------------------------------------------------------------------------
# Session notes update (LLM summarization)
# ---------------------------------------------------------------------------

async def update_session_notes(
    router,
    db_path: str,
    notes_path: str,
    role: str = "summarizer",
) -> None:
    """Ask the LLM to rewrite session notes based on current state.
    Swallows errors — this is fire-and-forget, never blocking."""
    try:
        from db.queries import get_plan, get_recent_history
        from datetime import date

        today = date.today().isoformat()
        try:
            plan = get_plan(db_path, today)
        except Exception:
            plan = {}
        history = get_recent_history(db_path, n=5)
        existing_notes = read_session_notes(notes_path) or _SESSION_NOTES_TEMPLATE

        history_text = "\n".join(
            f"[{h['role']}] {h['body']}" for h in history
        )

        prompt = (
            f"Update the session notes below based on recent activity.\n\n"
            f"Current plan summary: {_summarize_plan(plan)}\n\n"
            f"Recent conversation:\n{history_text}\n\n"
            f"Existing notes:\n{existing_notes}\n\n"
            f"Rewrite the session notes to reflect the current state. "
            f"Keep each section short and factual. Return only the updated notes."
        )

        response = await router.complete(
            role=role,
            messages=[{"role": "user", "content": prompt}],
            system="You are a concise note-taking assistant.",
        )
        write_session_notes(response.content, notes_path)
    except Exception as e:
        logger.warning("update_session_notes failed: %s", e)


# ---------------------------------------------------------------------------
# Anchor transition commit
# ---------------------------------------------------------------------------

async def commit_anchor_transition(
    router,
    db_path: str,
    anchor_id: str,
    notes_path: str,
    role: str = "summarizer",
) -> None:
    """Summarize what happened during an anchor and append to context_entries.
    Resets session notes for the next anchor."""
    try:
        from db.queries import get_plan, get_context_entries, upsert_context_entry
        from datetime import date

        today = date.today().isoformat()
        try:
            plan = get_plan(db_path, today)
            anchor_data = plan.get("anchors", {}).get(anchor_id, {})
            tasks = anchor_data.get("tasks", [])
        except Exception:
            tasks = []

        task_summary = "\n".join(
            f"- [{t.get('status','?')}] {t.get('text','')}" for t in tasks
        ) or "No tasks recorded."

        existing_notes = read_session_notes(notes_path) or ""

        prompt = (
            f"Write a brief factual summary (3-5 sentences) of the '{anchor_id}' time block.\n\n"
            f"Tasks:\n{task_summary}\n\n"
            f"Session notes:\n{existing_notes}\n\n"
            f"Focus on what was completed, what was left unfinished, and any notable context."
        )

        response = await router.complete(
            role=role,
            messages=[{"role": "user", "content": prompt}],
            system="You are a concise note-taking assistant.",
        )

        # Append summary to a per-anchor log in context_entries
        subject = f"Log/{today}/{anchor_id}"
        try:
            existing_entries = get_context_entries(db_path, prefix=subject)
            existing_body = next(
                (e["body"] for e in existing_entries if e["subject"] == subject), ""
            )
            upsert_context_entry(
                db_path, subject,
                (existing_body + "\n\n" + response.content).strip()
            )
        except Exception as e:
            logger.warning("commit_anchor_transition: failed to write context entry: %s", e)

        # Reset session notes for the next anchor
        write_session_notes("", notes_path)

    except Exception as e:
        logger.warning("commit_anchor_transition failed: %s", e)


# ---------------------------------------------------------------------------
# Significant mutation commit
# ---------------------------------------------------------------------------

async def commit_significant_mutations(
    router,
    db_path: str,
    changes: list[dict],
    notes_path: str,
    role: str = "summarizer",
    threshold: int = _SIGNIFICANT_MUTATION_THRESHOLD,
) -> None:
    """If enough mutations happened, summarize and update session notes.
    Does nothing if change count is below threshold."""
    if len(changes) < threshold:
        return

    try:
        changes_text = "\n".join(
            f"- [{c.get('type','change')}] {c.get('description','')}"
            for c in changes
        )
        existing_notes = read_session_notes(notes_path) or _SESSION_NOTES_TEMPLATE

        prompt = (
            f"The following changes were just made to the task system:\n{changes_text}\n\n"
            f"Update the 'Today's Progress' and 'Active Context' sections of these session notes "
            f"to reflect what changed. Return the complete updated notes.\n\n"
            f"Current notes:\n{existing_notes}"
        )

        response = await router.complete(
            role=role,
            messages=[{"role": "user", "content": prompt}],
            system="You are a concise note-taking assistant.",
        )
        write_session_notes(response.content, notes_path)
    except Exception as e:
        logger.warning("commit_significant_mutations failed: %s", e)


# ---------------------------------------------------------------------------
# Emergency compaction
# ---------------------------------------------------------------------------

def should_compact(
    messages: list[dict],
    context_limit: int = 200_000,
) -> bool:
    """Return True if the conversation is at or above 90% of context_limit.
    Uses a rough chars→tokens estimate (4 chars per token)."""
    total_chars = sum(len(str(m.get("content", ""))) for m in messages)
    estimated_tokens = total_chars / _CHARS_PER_TOKEN
    return estimated_tokens >= context_limit * _COMPACT_THRESHOLD


async def compact_conversation(
    messages: list[dict],
    router,
    role: str = "memory",
) -> list[dict]:
    """Emergency compaction: summarize history into a single synthetic message.
    Returns original messages unchanged if the LLM call fails."""
    try:
        history_text = "\n".join(
            f"[{m['role']}] {str(m.get('content', ''))[:500]}"
            for m in messages
        )
        prompt = (
            f"Summarize this conversation history concisely. "
            f"Preserve: decisions made, tasks updated, context changes, open questions.\n\n"
            f"{history_text}"
        )

        response = await router.complete(
            role=role,
            messages=[{"role": "user", "content": prompt}],
            system="You are a concise summarization assistant.",
        )

        summary_message = {
            "role": "user",
            "content": f"[Conversation summary — earlier history compacted]\n\n{response.content}",
        }
        return [summary_message]
    except Exception as e:
        logger.warning("compact_conversation failed: %s — returning original", e)
        return messages


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _summarize_plan(plan: dict) -> str:
    """Compact text representation of plan anchors and task statuses."""
    parts = []
    for anchor_id, anchor_data in plan.get("anchors", {}).items():
        tasks = anchor_data.get("tasks", [])
        task_strs = [f"[{t.get('status','?')[:1]}] {t.get('text','')}" for t in tasks]
        parts.append(f"{anchor_id}: {' | '.join(task_strs) or 'no tasks'}")
    return "\n".join(parts) or "No plan data."
