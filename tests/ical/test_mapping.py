"""Tests for integrations.ical.mapping — VEVENT → TaskDraft conversion."""
from datetime import datetime, timezone, timedelta

import pytest

# ICS fixtures as byte strings
_SIMPLE_EVENT = b"""\
BEGIN:VCALENDAR
VERSION:2.0
BEGIN:VEVENT
UID:simple-event-001@test
SUMMARY:Team standup
DESCRIPTION:Daily standup meeting
DTSTART:20260510T140000Z
DTEND:20260510T143000Z
URL:https://example.com/meeting
END:VEVENT
END:VCALENDAR
"""

_ALLDAY_EVENT = b"""\
BEGIN:VCALENDAR
VERSION:2.0
BEGIN:VEVENT
UID:allday-001@test
SUMMARY:Conference Day
DTSTART;VALUE=DATE:20260601
DTEND;VALUE=DATE:20260602
END:VEVENT
END:VCALENDAR
"""

_MULTIDAY_ALLDAY = b"""\
BEGIN:VCALENDAR
VERSION:2.0
BEGIN:VEVENT
UID:multiday-001@test
SUMMARY:Vacation
DTSTART;VALUE=DATE:20260601
DTEND;VALUE=DATE:20260605
END:VEVENT
END:VCALENDAR
"""

_RECURRING_EVENT = b"""\
BEGIN:VCALENDAR
VERSION:2.0
BEGIN:VEVENT
UID:weekly-standup@test
SUMMARY:Weekly standup
DTSTART;TZID=America/New_York:20260504T090000
DTEND;TZID=America/New_York:20260504T093000
RRULE:FREQ=WEEKLY;BYDAY=MO
END:VEVENT
END:VCALENDAR
"""

_CANCELLED_EVENT = b"""\
BEGIN:VCALENDAR
VERSION:2.0
BEGIN:VEVENT
UID:cancelled-001@test
SUMMARY:Cancelled meeting
DTSTART:20260510T140000Z
DTEND:20260510T150000Z
STATUS:CANCELLED
END:VEVENT
END:VCALENDAR
"""

_NO_TITLE_EVENT = b"""\
BEGIN:VCALENDAR
VERSION:2.0
BEGIN:VEVENT
UID:notitle-001@test
DTSTART:20260510T140000Z
DTEND:20260510T150000Z
END:VEVENT
END:VCALENDAR
"""

_MISSING_UID = b"""\
BEGIN:VCALENDAR
VERSION:2.0
BEGIN:VEVENT
SUMMARY:No UID event
DTSTART:20260510T140000Z
DTEND:20260510T150000Z
END:VEVENT
END:VCALENDAR
"""

_MISSING_DTSTART = b"""\
BEGIN:VCALENDAR
VERSION:2.0
BEGIN:VEVENT
UID:nodtstart-001@test
SUMMARY:No DTSTART
END:VEVENT
END:VCALENDAR
"""

_EXCEPTION_INSTANCE = b"""\
BEGIN:VCALENDAR
VERSION:2.0
BEGIN:VEVENT
UID:weekly-standup@test
SUMMARY:Standup (rescheduled)
DTSTART:20260511T100000Z
DTEND:20260511T103000Z
RECURRENCE-ID:20260511T090000Z
END:VEVENT
END:VCALENDAR
"""


def _get_vevent(ics_bytes: bytes):
    """Parse the first VEVENT from an ICS byte string."""
    import icalendar
    cal = icalendar.Calendar.from_ical(ics_bytes)
    for component in cal.walk():
        if component.name == "VEVENT":
            return component
    return None


class TestMapVevent:
    def test_simple_event_fields(self):
        from integrations.ical.mapping import map_vevent
        vevent = _get_vevent(_SIMPLE_EVENT)
        draft = map_vevent(vevent)

        assert draft is not None
        assert draft.title == "Team standup"
        assert draft.source == "ical"
        assert draft.external_id == "simple-event-001@test"
        assert draft.description == "Daily standup meeting"
        assert draft.external_url == "https://example.com/meeting"
        assert draft.source_status is None
        assert draft.rrule is None

        # Times should be UTC-aware datetimes
        expected_start = datetime(2026, 5, 10, 14, 0, 0, tzinfo=timezone.utc)
        expected_end = datetime(2026, 5, 10, 14, 30, 0, tzinfo=timezone.utc)
        assert draft.start_time == expected_start
        assert draft.end_time == expected_end

    def test_allday_event_maps_to_midnight_utc(self):
        from integrations.ical.mapping import map_vevent
        vevent = _get_vevent(_ALLDAY_EVENT)
        draft = map_vevent(vevent)

        assert draft is not None
        assert draft.start_time == datetime(2026, 6, 1, 0, 0, 0, tzinfo=timezone.utc)
        # DTEND is exclusive in iCal: DATE 2026-06-02 → midnight UTC − 1s
        assert draft.end_time == datetime(2026, 6, 1, 23, 59, 59, tzinfo=timezone.utc)

    def test_multiday_allday_end_minus_one_second(self):
        from integrations.ical.mapping import map_vevent
        vevent = _get_vevent(_MULTIDAY_ALLDAY)
        draft = map_vevent(vevent)

        # DTEND=2026-06-05 (exclusive) → stored end = 2026-06-04 23:59:59 UTC
        assert draft.end_time == datetime(2026, 6, 4, 23, 59, 59, tzinfo=timezone.utc)

    def test_recurring_event_has_rrule_and_dtstart_tzid(self):
        from integrations.ical.mapping import map_vevent
        vevent = _get_vevent(_RECURRING_EVENT)
        draft = map_vevent(vevent)

        assert draft.rrule is not None
        assert "RRULE:FREQ=WEEKLY" in draft.rrule
        assert "BYDAY=MO" in draft.rrule
        # DTSTART;TZID should be embedded for DST safety
        assert "DTSTART;TZID=America/New_York:" in draft.rrule

    def test_cancelled_event_sets_source_status(self):
        from integrations.ical.mapping import map_vevent
        vevent = _get_vevent(_CANCELLED_EVENT)
        draft = map_vevent(vevent)

        assert draft is not None
        assert draft.source_status == "cancelled"

    def test_no_summary_uses_default_title(self):
        from integrations.ical.mapping import map_vevent
        vevent = _get_vevent(_NO_TITLE_EVENT)
        draft = map_vevent(vevent)

        assert draft.title == "(No title)"

    def test_missing_uid_raises_value_error(self):
        from integrations.ical.mapping import map_vevent
        vevent = _get_vevent(_MISSING_UID)
        with pytest.raises(ValueError, match="UID"):
            map_vevent(vevent)

    def test_missing_dtstart_raises_value_error(self):
        from integrations.ical.mapping import map_vevent
        vevent = _get_vevent(_MISSING_DTSTART)
        with pytest.raises(ValueError, match="DTSTART"):
            map_vevent(vevent)

    def test_exception_instance_composite_external_id(self):
        from integrations.ical.mapping import map_vevent
        vevent = _get_vevent(_EXCEPTION_INSTANCE)
        draft = map_vevent(vevent)

        # External ID should be composite: UID::RECURRENCE-ID-iso
        assert "::" in draft.external_id
        assert draft.external_id.startswith("weekly-standup@test::")

        # recurrence_id should hold bare UID (points to master)
        assert draft.recurrence_id == "weekly-standup@test"

        # original_start_time should be the RECURRENCE-ID value
        assert draft.original_start_time == datetime(2026, 5, 11, 9, 0, 0, tzinfo=timezone.utc)


class TestParseIcsBytes:
    def test_masters_before_exceptions(self):
        """Masters must come before exception instances in the output list."""
        from integrations.ical.parser import parse_ics_bytes

        # Combine master + exception in reverse order in the file
        combined = b"""\
BEGIN:VCALENDAR
VERSION:2.0
BEGIN:VEVENT
UID:weekly-standup@test
SUMMARY:Standup (rescheduled)
DTSTART:20260511T100000Z
DTEND:20260511T103000Z
RECURRENCE-ID:20260511T090000Z
END:VEVENT
BEGIN:VEVENT
UID:weekly-standup@test
SUMMARY:Weekly standup
DTSTART;TZID=America/New_York:20260504T090000
DTEND;TZID=America/New_York:20260504T093000
RRULE:FREQ=WEEKLY;BYDAY=MO
END:VEVENT
END:VCALENDAR
"""
        drafts, errors = parse_ics_bytes(combined)
        assert len(errors) == 0
        assert len(drafts) == 2
        # Master (no RECURRENCE-ID) must come first
        assert drafts[0].recurrence_id is None
        assert drafts[1].recurrence_id is not None

    def test_malformed_event_goes_to_errors(self):
        from integrations.ical.parser import parse_ics_bytes
        drafts, errors = parse_ics_bytes(_MISSING_UID)
        assert len(drafts) == 0
        assert len(errors) == 1
        assert "UID" in errors[0]["error"]

    def test_cancelled_event_included_in_drafts(self):
        """Cancelled events should be in drafts (not errors) so the route can handle them."""
        from integrations.ical.parser import parse_ics_bytes
        drafts, errors = parse_ics_bytes(_CANCELLED_EVENT)
        assert len(errors) == 0
        assert len(drafts) == 1
        assert drafts[0].source_status == "cancelled"

    def test_multiple_events_parsed(self):
        combined = b"""\
BEGIN:VCALENDAR
VERSION:2.0
BEGIN:VEVENT
UID:event-a@test
SUMMARY:Event A
DTSTART:20260510T140000Z
DTEND:20260510T150000Z
END:VEVENT
BEGIN:VEVENT
UID:event-b@test
SUMMARY:Event B
DTSTART:20260511T090000Z
DTEND:20260511T100000Z
END:VEVENT
END:VCALENDAR
"""
        from integrations.ical.parser import parse_ics_bytes
        drafts, errors = parse_ics_bytes(combined)
        assert len(drafts) == 2
        assert len(errors) == 0
        uids = {d.external_id for d in drafts}
        assert uids == {"event-a@test", "event-b@test"}

    def test_invalid_ics_raises_value_error(self):
        from integrations.ical.parser import parse_ics_bytes
        with pytest.raises(ValueError, match="valid iCalendar"):
            parse_ics_bytes(b"not an ics file at all")

    def test_1001_events_truncated_to_1000(self):
        """Files with > 1000 VEVENTs should only return first 1000."""
        events = []
        for i in range(1001):
            events.append(f"""\
BEGIN:VEVENT
UID:event-{i}@test
SUMMARY:Event {i}
DTSTART:20260510T140000Z
DTEND:20260510T150000Z
END:VEVENT""")
        ics = ("BEGIN:VCALENDAR\nVERSION:2.0\n" + "\n".join(events) + "\nEND:VCALENDAR\n").encode()
        from integrations.ical.parser import parse_ics_bytes
        drafts, errors = parse_ics_bytes(ics)
        assert len(drafts) == 1000
