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
