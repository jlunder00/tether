"""iCal ICS byte stream → list[TaskDraft] parser.

Processing order guarantees masters before exception instances so the route
handler can upsert masters first (required for DB recurrence_id integrity).
"""
from __future__ import annotations

import logging

from integrations.models import TaskDraft

_MAX_EVENTS = 1000
_logger = logging.getLogger(__name__)


def parse_ics_bytes(raw: bytes) -> tuple[list[TaskDraft], list[dict]]:
    """Parse raw ICS content and return (drafts, errors).

    Masters (no RECURRENCE-ID) are yielded before exception instances.
    Malformed VEVENTs are collected as {"uid": ..., "error": ...} dicts.
    Raises ValueError for content that isn't a valid iCalendar file at all.
    """
    import icalendar

    try:
        cal = icalendar.Calendar.from_ical(raw)
    except Exception as exc:
        raise ValueError(f"Not a valid iCalendar file: {exc}") from exc

    # Verify we got something calendar-shaped
    if not hasattr(cal, "walk"):
        raise ValueError("Not a valid iCalendar file: no components found")

    from integrations.ical.mapping import map_vevent

    masters: list[TaskDraft] = []
    exceptions: list[TaskDraft] = []
    errors: list[dict] = []
    total = 0

    for component in cal.walk():
        if component.name != "VEVENT":
            continue

        total += 1
        if total > _MAX_EVENTS:
            # Caller can detect truncation by checking len(drafts) == 1000
            _logger.warning("ICS file exceeds %d events; truncating", _MAX_EVENTS)
            break

        try:
            draft = map_vevent(component)
        except ValueError as exc:
            uid_raw = component.get("UID")
            summary_raw = component.get("SUMMARY")
            identifier = str(uid_raw) if uid_raw else str(summary_raw or "(unknown)")
            errors.append({"uid": identifier, "error": str(exc)})
            continue

        if draft is None:
            continue

        if draft.recurrence_id is not None:
            exceptions.append(draft)
        else:
            masters.append(draft)

    return masters + exceptions, errors
