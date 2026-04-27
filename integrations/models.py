"""Shared dataclasses for the integration framework."""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime


@dataclass
class TaskDraft:
    """Normalised representation of an event from any integration source.

    Routes and the sync worker convert these into actual task rows.
    """

    title: str
    source: str          # e.g. "google_calendar"
    external_id: str

    start_time: datetime | None = None
    end_time: datetime | None = None
    description: str | None = None
    external_url: str | None = None
    source_status: str | None = None   # "cancelled" triggers soft-delete

    # Recurrence fields (Google Calendar recurring events)
    rrule: str | None = None                          # e.g. "RRULE:FREQ=WEEKLY;BYDAY=MO"
    recurrence_id: str | None = None                  # GCal recurringEventId (exception instances)
    exdates: list[str] = field(default_factory=list)  # EXDATE lines from recurrence array
    original_start_time: datetime | None = None       # originalStartTime for moved exceptions


@dataclass
class WebhookPayload:
    """Parsed Google Calendar push-notification headers."""

    channel_id: str
    resource_id: str
    resource_state: str          # "sync" | "exists" | "not_exists"
    expiration: datetime | None = None
    raw_headers: dict = field(default_factory=dict)
