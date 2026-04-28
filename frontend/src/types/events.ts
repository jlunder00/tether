// Event entity — mirrors the planned DB schema.
// Backend endpoints (GET/POST/PATCH /api/events) are not yet implemented;
// the store uses fixture data until the backend ships.
// Assumed API contract:
//   GET  /api/events?start=ISO&end=ISO  → CalendarEvent[]
//   POST /api/events                    → CalendarEvent  (promote task to event)
//   PATCH /api/events/:id               → CalendarEvent
//   DELETE /api/events/:id/time-constraint → void  (demote back to plain task)
//
// Note: backend contract uses numeric ids; frontend uses string ids throughout.
// ID type reconciliation is tracked separately.

export type EventSource = 'tether' | 'google_calendar' | 'ical'

export interface CalendarEvent {
  id: string
  title: string
  start_time: string   // ISO 8601
  end_time: string     // ISO 8601
  source: EventSource
  external_id: string | null
  task_id: string | null  // FK to task if promoted; null for standalone/synced
  anchor_id: string | null
  color: string | null
  /** True when this event is the master of a recurring series. Mutually exclusive with is_occurrence. */
  is_recurring: boolean
  /** True when this event is a synthesized occurrence from an rrule expansion. Mutually exclusive with is_recurring. */
  is_occurrence: boolean
  /** RRULE string (e.g. "FREQ=WEEKLY;BYDAY=MO"). Non-null only on master events (is_recurring === true). */
  rrule: string | null
  /** True when this event spans the full day and has no specific start/end time. */
  is_all_day: boolean
  /** context_subject of the linked task, if any. Populated by backend (get_events_for_range). */
  context_subject: string | null
}
