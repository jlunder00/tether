"""iCal VEVENT → TaskDraft mapping.

Mirrors integrations/google_calendar/mapping.py in structure.
Reuses _prepend_dtstart_tzid from the GCal mapping for DST-safe RRULE storage.
"""
from __future__ import annotations

import logging
import re
from datetime import date, datetime, timedelta, timezone

from integrations.models import TaskDraft

_SOURCE = "ical"
_HTML_TAG_RE = re.compile(r"<[^>]+>")
_logger = logging.getLogger(__name__)


def _strip_html(text: str | None) -> str | None:
    if not text:
        return text
    return _HTML_TAG_RE.sub("", text).strip() or None


def _to_utc(dt: datetime) -> datetime:
    """Normalise a datetime to UTC-aware. Floating datetimes are treated as UTC."""
    if dt.tzinfo is None:
        _logger.warning("Floating datetime treated as UTC: %s", dt)
        return dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc)


def _decode_dt(component, prop: str) -> datetime | date | None:
    """Decode a date/datetime property from a VEVENT component.

    Returns a datetime (UTC-aware) or a date object (for VALUE=DATE properties),
    or None if the property is absent.
    """
    raw = component.get(prop)
    if raw is None:
        return None
    try:
        value = raw.dt
    except AttributeError:
        value = raw
    return value


def _date_to_midnight_utc(d: date) -> datetime:
    return datetime(d.year, d.month, d.day, tzinfo=timezone.utc)


def map_vevent(component) -> TaskDraft | None:
    """Convert an icalendar VEVENT component to a TaskDraft.

    Returns None for STATUS:CANCELLED events that should just be skipped
    (caller decides). Sets source_status='cancelled' so the upsert can
    mark existing rows.

    Raises ValueError for events missing required UID or DTSTART.
    """
    # ── Required fields ──────────────────────────────────────────────────────
    uid_raw = component.get("UID")
    if not uid_raw:
        raise ValueError("VEVENT missing required UID")
    uid = str(uid_raw)

    dtstart_raw = _decode_dt(component, "DTSTART")
    if dtstart_raw is None:
        raise ValueError(f"VEVENT {uid!r} missing required DTSTART")

    # ── Optional display fields ───────────────────────────────────────────────
    title = str(component.get("SUMMARY") or "(No title)")
    description = _strip_html(str(component.get("DESCRIPTION") or "") or None)
    url_raw = component.get("URL")
    external_url = str(url_raw) if url_raw else None

    # ── Status ────────────────────────────────────────────────────────────────
    status_raw = component.get("STATUS")
    source_status = "cancelled" if (status_raw and str(status_raw).upper() == "CANCELLED") else None

    # ── DTSTART / DTEND / DURATION → start_time, end_time ────────────────────
    is_all_day = isinstance(dtstart_raw, date) and not isinstance(dtstart_raw, datetime)

    if is_all_day:
        start_time = _date_to_midnight_utc(dtstart_raw)
        dtend_raw = _decode_dt(component, "DTEND")
        if dtend_raw is not None and isinstance(dtend_raw, date) and not isinstance(dtend_raw, datetime):
            # DATE DTEND is exclusive in RFC 5545 — subtract 1 second to get inclusive end
            end_time = _date_to_midnight_utc(dtend_raw) - timedelta(seconds=1)
        else:
            # No DTEND — default all-day event end to end of same day
            end_time = start_time + timedelta(hours=24) - timedelta(seconds=1)
    else:
        start_time = _to_utc(dtstart_raw)
        dtend_raw = _decode_dt(component, "DTEND")
        if dtend_raw is not None and isinstance(dtend_raw, datetime):
            end_time = _to_utc(dtend_raw)
        elif dtend_raw is not None and isinstance(dtend_raw, date):
            end_time = _date_to_midnight_utc(dtend_raw) - timedelta(seconds=1)
        else:
            # Try DURATION
            duration_raw = component.get("DURATION")
            if duration_raw is not None:
                try:
                    end_time = start_time + duration_raw.dt
                except Exception:
                    end_time = start_time + timedelta(hours=1)
            else:
                # No DTEND or DURATION — default to 1 hour
                end_time = start_time + timedelta(hours=1)

    # ── Recurrence ────────────────────────────────────────────────────────────
    rrule = None
    rrule_raw = component.get("RRULE")
    if rrule_raw is not None:
        rrule_str = "RRULE:" + rrule_raw.to_ical().decode()
        # Embed DTSTART;TZID for DST-safe wall-clock expansion (same as GCal mapping)
        if not is_all_day:
            dtstart_prop = component.get("DTSTART")
            tzid = getattr(getattr(dtstart_prop, "params", {}), "get", lambda *_: None)("TZID")
            if tzid and start_time:
                from integrations.google_calendar.mapping import _prepend_dtstart_tzid
                rrule_str = _prepend_dtstart_tzid(rrule_str, start_time, tzid)
        rrule = rrule_str

    # Exdates
    exdates: list[str] = []
    exdate_raw = component.get("EXDATE")
    if exdate_raw is not None:
        if not isinstance(exdate_raw, list):
            exdate_raw = [exdate_raw]
        for ex in exdate_raw:
            exdates.append("EXDATE:" + ex.to_ical().decode())

    # ── Exception instance (RECURRENCE-ID) ───────────────────────────────────
    recurrence_id_raw = component.get("RECURRENCE-ID")
    if recurrence_id_raw is not None:
        # Composite external_id: UID::RECURRENCE-ID-iso
        rec_dt = recurrence_id_raw.dt
        if isinstance(rec_dt, datetime):
            rec_iso = _to_utc(rec_dt).strftime("%Y%m%dT%H%M%SZ")
        else:
            rec_iso = rec_dt.isoformat().replace("-", "")
        external_id = f"{uid}::{rec_iso}"
        recurrence_id = uid  # points back to the master's external_id
        original_start_time: datetime | None
        if isinstance(rec_dt, datetime):
            original_start_time = _to_utc(rec_dt)
        else:
            original_start_time = _date_to_midnight_utc(rec_dt)
    else:
        external_id = uid
        recurrence_id = None
        original_start_time = None

    return TaskDraft(
        title=title,
        source=_SOURCE,
        external_id=external_id,
        start_time=start_time,
        end_time=end_time,
        description=description,
        external_url=external_url,
        source_status=source_status,
        rrule=rrule,
        recurrence_id=recurrence_id,
        exdates=exdates,
        original_start_time=original_start_time,
    )
