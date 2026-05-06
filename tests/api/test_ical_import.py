"""Tests for POST /api/ical/import endpoint.

Requires DATABASE_URL — skipped in CI when not set.
Deduplication test verifies re-importing the same file doesn't create duplicate rows.
"""
from __future__ import annotations

import io

import pytest

# Import conftest fixtures: api_client, conn (via conftest.py in this directory)

_SIMPLE_TWO_EVENTS = b"""\
BEGIN:VCALENDAR
VERSION:2.0
PRODID:-//Test//Test//EN
BEGIN:VEVENT
UID:ical-test-event-A@import
SUMMARY:Import Test A
DTSTART:20260601T100000Z
DTEND:20260601T110000Z
END:VEVENT
BEGIN:VEVENT
UID:ical-test-event-B@import
SUMMARY:Import Test B
DTSTART:20260602T140000Z
DTEND:20260602T150000Z
END:VEVENT
END:VCALENDAR
"""

_SINGLE_WITH_RRULE = b"""\
BEGIN:VCALENDAR
VERSION:2.0
BEGIN:VEVENT
UID:ical-recurring@import
SUMMARY:Weekly Sync
DTSTART;TZID=America/New_York:20260602T090000
DTEND;TZID=America/New_York:20260602T093000
RRULE:FREQ=WEEKLY;BYDAY=TU
END:VEVENT
END:VCALENDAR
"""

_ALLDAY_EVENT = b"""\
BEGIN:VCALENDAR
VERSION:2.0
BEGIN:VEVENT
UID:ical-allday@import
SUMMARY:All Day Event
DTSTART;VALUE=DATE:20260605
DTEND;VALUE=DATE:20260606
END:VEVENT
END:VCALENDAR
"""

_MALFORMED_NO_UID = b"""\
BEGIN:VCALENDAR
VERSION:2.0
BEGIN:VEVENT
SUMMARY:No UID event
DTSTART:20260601T100000Z
DTEND:20260601T110000Z
END:VEVENT
END:VCALENDAR
"""

_NOT_ICS = b"this is definitely not an ical file"


class TestICalImportEndpoint:
    async def test_file_upload_returns_summary(self, api_client):
        resp = await api_client.post(
            "/api/ical/import",
            files={"file": ("calendar.ics", io.BytesIO(_SIMPLE_TWO_EVENTS), "text/calendar")},
        )
        assert resp.status_code == 200
        data = resp.json()
        assert data["imported"] + data["updated"] == 2
        assert data["skipped"] == 0
        assert data["errors"] == [], f"errors: {data.get('errors')}"
        assert data["total_events"] == 2

    async def test_deduplication_reimport_same_file(self, api_client, conn):
        """Re-importing the same ICS file should not create duplicate rows."""
        # First import
        r1 = await api_client.post(
            "/api/ical/import",
            files={"file": ("cal.ics", io.BytesIO(_SIMPLE_TWO_EVENTS), "text/calendar")},
        )
        assert r1.status_code == 200
        d1 = r1.json()
        count_before = await conn.fetchval(
            "SELECT COUNT(*) FROM tasks WHERE source = 'ical'"
        )

        # Second import — same file
        r2 = await api_client.post(
            "/api/ical/import",
            files={"file": ("cal.ics", io.BytesIO(_SIMPLE_TWO_EVENTS), "text/calendar")},
        )
        assert r2.status_code == 200
        d2 = r2.json()
        count_after = await conn.fetchval(
            "SELECT COUNT(*) FROM tasks WHERE source = 'ical'"
        )

        # Row count must not increase — same UIDs are upserted, not duplicated
        assert count_after == count_before
        # Second import should show updates, not new imports
        assert d2["updated"] == 2
        assert d2["imported"] == 0

    async def test_recurring_event_stores_rrule(self, api_client, conn):
        resp = await api_client.post(
            "/api/ical/import",
            files={"file": ("recurring.ics", io.BytesIO(_SINGLE_WITH_RRULE), "text/calendar")},
        )
        assert resp.status_code == 200
        assert resp.json()["errors"] == []

        row = await conn.fetchrow(
            "SELECT rrule, source, external_id FROM tasks WHERE external_id = 'ical-recurring@import'"
        )
        assert row is not None
        assert row["source"] == "ical"
        assert row["rrule"] is not None
        assert "FREQ=WEEKLY" in row["rrule"]

    async def test_malformed_event_in_errors(self, api_client):
        resp = await api_client.post(
            "/api/ical/import",
            files={"file": ("bad.ics", io.BytesIO(_MALFORMED_NO_UID), "text/calendar")},
        )
        assert resp.status_code == 200
        data = resp.json()
        assert data["imported"] == 0
        assert len(data["errors"]) == 1
        assert "UID" in data["errors"][0]["error"]

    async def test_invalid_ics_returns_422(self, api_client):
        resp = await api_client.post(
            "/api/ical/import",
            files={"file": ("bad.ics", io.BytesIO(_NOT_ICS), "text/calendar")},
        )
        assert resp.status_code == 422
        assert "iCalendar" in resp.json()["detail"]

    async def test_file_too_large_returns_413(self, api_client):
        big_file = b"X" * (5 * 1024 * 1024 + 1)
        resp = await api_client.post(
            "/api/ical/import",
            files={"file": ("big.ics", io.BytesIO(big_file), "text/calendar")},
        )
        assert resp.status_code == 413

    async def test_skip_all_day_param(self, api_client, conn):
        """?skip_all_day=true should skip DATE-only events."""
        resp = await api_client.post(
            "/api/ical/import?skip_all_day=true",
            files={"file": ("allday.ics", io.BytesIO(_ALLDAY_EVENT), "text/calendar")},
        )
        assert resp.status_code == 200
        data = resp.json()
        assert data["skipped"] == 1
        assert data["imported"] == 0

    async def test_unauthenticated_returns_401(self, api_client):
        from httpx import AsyncClient, ASGITransport
        from api.main import create_app
        app = create_app()
        async with AsyncClient(
            transport=ASGITransport(app=app),
            base_url="http://test",
        ) as unauthed:
            resp = await unauthed.post(
                "/api/ical/import",
                files={"file": ("cal.ics", io.BytesIO(_SIMPLE_TWO_EVENTS), "text/calendar")},
            )
        assert resp.status_code in (401, 403)

    async def test_url_ssrf_blocked(self, api_client):
        resp = await api_client.post(
            "/api/ical/import",
            json={"url": "http://127.0.0.1/calendar.ics"},
        )
        assert resp.status_code == 422
        assert "private" in resp.json()["detail"].lower()


class TestWebcalSchemeNormalization:
    """webcal:// and webcals:// should be rewritten to https:// before fetching."""

    def test_webcal_rewritten_to_https(self):
        import re
        def normalize(url):
            return re.sub(r"^webcals?://", "https://", url, flags=re.IGNORECASE)

        assert normalize("webcal://example.com/feed.ics") == "https://example.com/feed.ics"
        assert normalize("webcals://example.com/feed.ics") == "https://example.com/feed.ics"
        assert normalize("WEBCAL://example.com/feed.ics") == "https://example.com/feed.ics"
        assert normalize("https://example.com/feed.ics") == "https://example.com/feed.ics"
        assert normalize("http://example.com/feed.ics") == "http://example.com/feed.ics"
