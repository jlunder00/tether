// Event entity — mirrors the planned DB schema.
// Backend endpoints (GET/POST/PATCH /api/events) are not yet implemented;
// the store uses fixture data until the backend ships.
// Assumed API contract:
//   GET  /api/events?start=ISO&end=ISO  → CalendarEvent[]
//   POST /api/events                    → CalendarEvent  (promote task to event)
//   PATCH /api/events/:id               → CalendarEvent
//   DELETE /api/events/:id/time-constraint → void  (demote back to plain task)

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
}
