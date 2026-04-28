export type RecurrenceEditScope = 'this' | 'this_and_future' | 'all'

export type PendingRecurrence =
  | { kind: 'event-move'; eventId: string; startTime: string; endTime: string; originalStartTime: string }
  | { kind: 'event-edit'; eventId: string; patch: Record<string, unknown> }
  | { kind: 'event-delete'; eventId: string; originalStartTime: string }
  | { kind: 'task-edit' | 'task-move' | 'task-delete'; taskId: string }
  | null
