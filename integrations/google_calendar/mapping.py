"""Google Calendar event → TaskDraft field mapping.

Mapping table (from design doc Section 3):

| Google field                        | Task field   | Notes                       |
|-------------------------------------|--------------|-----------------------------|
| summary                             | title        | direct                      |
| description                         | description  | strip HTML                  |
| start.dateTime / start.date         | start_time   | all-day: midnight local      |
| end.dateTime / end.date             | end_time     | all-day: midnight+24h local  |
| conferenceData.entryPoints[].uri    | external_url | prefer Meet link             |
| htmlLink                            | external_url | fallback if no conf link     |
| id                                  | external_id  |                              |
| 'google_calendar'                   | source       | literal                      |
| status: 'cancelled'                 | → soft delete| source_status='cancelled'    |
"""
from __future__ import annotations

import re
from datetime import datetime, timedelta, timezone
from urllib.parse import urlparse

from integrations.models import TaskDraft

_SOURCE = "google_calendar"

# Minimal HTML-tag stripper (not a full sanitiser — descriptions are plain-ish)
_HTML_TAG_RE = re.compile(r"<[^>]+>")


def _strip_html(text: str | None) -> str | None:
    if not text:
        return text
    return _HTML_TAG_RE.sub("", text).strip() or None


def _parse_dt(dt_field: dict | None) -> datetime | None:
    """Parse a Google Calendar dateTime or date field into a UTC datetime."""
    if not dt_field:
        return None
    if "dateTime" in dt_field:
        raw = dt_field["dateTime"]
        dt = datetime.fromisoformat(raw)
        # Ensure timezone-aware; Google always sends timezone info but be safe.
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)
        return dt.astimezone(timezone.utc)
    if "date" in dt_field:
        # All-day event: midnight UTC on that date
        from datetime import date as _date
        d = _date.fromisoformat(dt_field["date"])
        return datetime(d.year, d.month, d.day, tzinfo=timezone.utc)
    return None


def _is_meet_link(url: str) -> bool:
    """Return True only if url's hostname is exactly meet.google.com."""
    try:
        parsed = urlparse(url)
        return parsed.scheme in ("https", "http") and parsed.netloc == "meet.google.com"
    except Exception:
        return False


def _conference_url(event: dict) -> str | None:
    """Return the first Meet/video link from conferenceData, if any."""
    conf = event.get("conferenceData", {})
    for ep in conf.get("entryPoints", []):
        uri = ep.get("uri", "")
        if _is_meet_link(uri) or ep.get("entryPointType") == "video":
            return uri
    return None


def _extract_recurrence(raw: dict) -> tuple[str | None, list[str]]:
    """Extract RRULE string and EXDATE lines from a GCal event's recurrence array.

    Returns (rrule, exdates) where:
    - rrule: the first "RRULE:..." line joined as a single string, or None
    - exdates: all lines starting with "EXDATE"
    """
    lines: list[str] = raw.get("recurrence") or []
    rrule_lines = [l for l in lines if l.startswith("RRULE:")]
    exdate_lines = [l for l in lines if l.startswith("EXDATE")]
    rrule = rrule_lines[0] if rrule_lines else None
    return rrule, exdate_lines


def _prepend_dtstart_tzid(rrule: str, start_dt: datetime, tzid: str) -> str:
    """Prepend a DTSTART;TZID line to an RRULE string.

    This preserves wall-clock time semantics across DST transitions. Without it,
    dateutil's rrulestr anchors expansion at UTC and a "9am Eastern" winter event
    becomes "10am Eastern" (14:00 UTC) after DST springs forward.

    The embedded DTSTART overrides the dtstart= keyword argument in rrulestr()
    calls, so expand_recurring() picks it up automatically.

    Example output:
        DTSTART;TZID=America/New_York:20260209T090000
        RRULE:FREQ=WEEKLY
    """
    import zoneinfo
    try:
        tz = zoneinfo.ZoneInfo(tzid)
    except (KeyError, zoneinfo.ZoneInfoNotFoundError):
        # Unknown IANA name — fall back to bare RRULE (no DST correction)
        return rrule
    local_dt = start_dt.astimezone(tz)
    dtstart_line = f"DTSTART;TZID={tzid}:{local_dt.strftime('%Y%m%dT%H%M%S')}"
    return f"{dtstart_line}\n{rrule}"


def map_event(raw: dict) -> TaskDraft:
    """Convert a raw Google Calendar event dict to a TaskDraft.

    Handles:
    - Regular and all-day events
    - Conference links (Meet preferred, htmlLink fallback)
    - Cancelled status → source_status='cancelled'
    - Recurring series: extracts rrule and exdates from recurrence array
    - Exception instances: extracts recurringEventId → recurrence_id
    """
    title = raw.get("summary") or "(No title)"
    external_id = raw.get("id")
    if not external_id:
        raise ValueError(f"Google Calendar event missing 'id' field: {raw!r}")
    description = _strip_html(raw.get("description"))

    start_time = _parse_dt(raw.get("start"))
    end_dt = _parse_dt(raw.get("end"))

    # All-day multi-day: end.date is exclusive in Google API, shift back 1 second
    # so end_time represents the last moment of the event.
    end_field = raw.get("end", {})
    if "date" in end_field and "dateTime" not in end_field and end_dt is not None:
        end_dt = end_dt - timedelta(seconds=1)

    external_url = _conference_url(raw) or raw.get("htmlLink")

    source_status = "cancelled" if raw.get("status") == "cancelled" else None

    rrule, exdates = _extract_recurrence(raw)
    # Embed DTSTART;TZID in the stored rrule so expand_recurring() uses wall-clock
    # semantics and produces the correct time after DST transitions.
    # Only recurring master events (rrule set, no recurrence_id) carry a timeZone.
    tz_id: str | None = raw.get("start", {}).get("timeZone")
    if rrule and tz_id and start_time:
        rrule = _prepend_dtstart_tzid(rrule, start_time, tz_id)

    recurrence_id: str | None = raw.get("recurringEventId")
    original_start_time = _parse_dt(raw.get("originalStartTime"))

    return TaskDraft(
        title=title,
        source=_SOURCE,
        external_id=external_id,
        start_time=start_time,
        end_time=end_dt,
        description=description,
        external_url=external_url,
        source_status=source_status,
        rrule=rrule,
        recurrence_id=recurrence_id,
        exdates=exdates,
        original_start_time=original_start_time,
    )
