"""Tests for integrations/google_calendar/mapping.py — URL parsing, event mapping."""
from __future__ import annotations

import pytest
from integrations.google_calendar.mapping import map_event, _conference_url


# ── _conference_url — Meet link extraction ────────────────────────────────────

def _make_event(uri: str, entry_point_type: str = "video") -> dict:
    return {
        "conferenceData": {
            "entryPoints": [{"uri": uri, "entryPointType": entry_point_type}]
        }
    }


def test_valid_meet_link_accepted():
    event = _make_event("https://meet.google.com/abc-defg-hij")
    assert _conference_url(event) == "https://meet.google.com/abc-defg-hij"


def test_spoofed_meet_link_in_query_param_rejected():
    """https://evil.com?r=https://meet.google.com must NOT match — hostname is evil.com.

    Uses entryPointType='phone' to isolate the Meet hostname check (video type
    accepts any URI by design — the spoof is specifically about faking a Meet URL).
    """
    event = _make_event("https://evil.com?r=https://meet.google.com", entry_point_type="phone")
    assert _conference_url(event) is None


def test_spoofed_meet_link_as_subdomain_rejected():
    """https://meet.google.com.evil.com must NOT match — startswith would accept this."""
    event = _make_event("https://meet.google.com.evil.com/trap", entry_point_type="phone")
    assert _conference_url(event) is None


def test_http_meet_link_accepted():
    """http:// scheme is also valid (non-HTTPS Meet links are rare but permitted)."""
    event = _make_event("http://meet.google.com/xyz")
    assert _conference_url(event) == "http://meet.google.com/xyz"


def test_non_meet_video_endpoint_accepted_by_type():
    """Non-Meet video entry points (e.g. Zoom) are accepted via entryPointType==video."""
    event = _make_event("https://zoom.us/j/12345", entry_point_type="video")
    assert _conference_url(event) == "https://zoom.us/j/12345"


def test_no_conference_data_returns_none():
    assert _conference_url({}) is None


def test_empty_entry_points_returns_none():
    assert _conference_url({"conferenceData": {"entryPoints": []}}) is None


# ── map_event — conference URL flows through to external_url ──────────────────

def test_map_event_spoofed_meet_url_not_used_as_external_url():
    """A spoofed Meet URL in conferenceData must not appear as external_url."""
    raw = {
        "summary": "Evil meeting",
        "id": "evil-id",
        "start": {"dateTime": "2026-04-24T10:00:00+00:00"},
        "end": {"dateTime": "2026-04-24T11:00:00+00:00"},
        "conferenceData": {
            "entryPoints": [
                {"uri": "https://meet.google.com.evil.com/trap", "entryPointType": "phone"}
            ]
        },
        "htmlLink": "https://calendar.google.com/event?eid=safe",
    }
    draft = map_event(raw)
    # Should fall back to htmlLink, not the spoofed URI
    assert draft.external_url == "https://calendar.google.com/event?eid=safe"


# ── map_event — RRULE / recurrence fields ─────────────────────────────────────

def _recurring_event(rrule: str = "RRULE:FREQ=WEEKLY;BYDAY=MO,WE,FR") -> dict:
    return {
        "summary": "Weekly standup",
        "id": "series-master-1",
        "start": {"dateTime": "2026-04-28T09:00:00+00:00"},
        "end": {"dateTime": "2026-04-28T09:30:00+00:00"},
        "recurrence": [rrule, "EXDATE;TZID=UTC:20260505T090000Z"],
    }


def test_map_event_extracts_rrule():
    """map_event sets draft.rrule from the recurrence array."""
    draft = map_event(_recurring_event("RRULE:FREQ=WEEKLY;BYDAY=MO,WE,FR"))
    assert draft.rrule == "RRULE:FREQ=WEEKLY;BYDAY=MO,WE,FR"


def test_map_event_no_recurrence_rrule_is_none():
    """Non-recurring event has draft.rrule == None."""
    raw = {
        "summary": "One-off",
        "id": "evt-once",
        "start": {"dateTime": "2026-04-28T09:00:00+00:00"},
        "end": {"dateTime": "2026-04-28T10:00:00+00:00"},
    }
    draft = map_event(raw)
    assert draft.rrule is None


def test_map_event_extracts_exdates():
    """EXDATE lines from recurrence array land in draft.exdates."""
    raw = {
        "summary": "Series",
        "id": "s1",
        "start": {"dateTime": "2026-04-28T09:00:00+00:00"},
        "end": {"dateTime": "2026-04-28T10:00:00+00:00"},
        "recurrence": [
            "RRULE:FREQ=WEEKLY",
            "EXDATE;TZID=UTC:20260505T090000Z",
            "EXDATE;TZID=UTC:20260512T090000Z",
        ],
    }
    draft = map_event(raw)
    assert len(draft.exdates) == 2
    assert "EXDATE;TZID=UTC:20260505T090000Z" in draft.exdates


def test_map_event_no_exdates_is_empty_list():
    """Events with no EXDATE lines have draft.exdates == []."""
    raw = {
        "summary": "Series no exdate",
        "id": "s2",
        "start": {"dateTime": "2026-04-28T09:00:00+00:00"},
        "end": {"dateTime": "2026-04-28T10:00:00+00:00"},
        "recurrence": ["RRULE:FREQ=DAILY"],
    }
    draft = map_event(raw)
    assert draft.exdates == []


def test_map_event_extracts_recurring_event_id():
    """Exception instances carry recurringEventId → draft.recurrence_id."""
    raw = {
        "summary": "Exception instance",
        "id": "exception-1",
        "recurringEventId": "series-master-1",
        "start": {"dateTime": "2026-05-05T10:00:00+00:00"},
        "end": {"dateTime": "2026-05-05T10:30:00+00:00"},
    }
    draft = map_event(raw)
    assert draft.recurrence_id == "series-master-1"


def test_map_event_recurrence_id_none_for_regular():
    """Regular non-exception events have draft.recurrence_id == None."""
    raw = {
        "summary": "Regular",
        "id": "r1",
        "start": {"dateTime": "2026-04-28T09:00:00+00:00"},
        "end": {"dateTime": "2026-04-28T10:00:00+00:00"},
    }
    draft = map_event(raw)
    assert draft.recurrence_id is None
