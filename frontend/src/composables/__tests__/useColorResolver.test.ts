import { describe, it, expect } from 'vitest'
import { resolveEventColor } from '../useColorResolver'
import type { CalendarEvent } from '../../types/events'
import type { Milestone } from '../../stores/milestones'
import type { ContextNode } from '../../stores/context'

function makeEvent(overrides: Partial<CalendarEvent> = {}): CalendarEvent {
  return {
    id: '1', title: 'Test',
    start_time: '2026-04-27T09:00:00', end_time: '2026-04-27T10:00:00',
    source: 'tether', external_id: null, task_id: 'task-1',
    anchor_id: null, color: null,
    is_recurring: false, is_occurrence: false, rrule: null,
    context_subject: null,
    ...overrides,
  }
}

const MILESTONES: Milestone[] = [
  { id: 'm1', context_subject: 'p', name: 'Alpha', description: null, target_date: null, status: 'pending', status_override: false, color: '#ff0000', created_at: '', updated_at: '', task_count: 1, done_count: 0, task_ids: ['task-1'], tasks: [] },
]
const CONTEXT_NODES: Record<string, ContextNode> = {
  'n1': { id: 'n1', parent_id: null, name: 'Work', description: null, node_type: 'context', archived: false, target_date: null, status: null, status_override: false, color: '#00ff00', created_at: '', updated_at: '' },
}

describe('resolveEventColor', () => {
  it('returns event.color when set', () => {
    expect(resolveEventColor(makeEvent({ color: '#abc123' }), [], {})).toBe('#abc123')
  })

  it('falls back to milestone color', () => {
    expect(resolveEventColor(makeEvent(), MILESTONES, {})).toBe('#ff0000')
  })

  it('falls back to context node color when context_subject matches node name', () => {
    const ev = makeEvent({ task_id: null, context_subject: 'Work' })
    expect(resolveEventColor(ev, [], CONTEXT_NODES)).toBe('#00ff00')
  })

  it('returns default indigo when no color anywhere', () => {
    expect(resolveEventColor(makeEvent({ task_id: 'no-milestone-task' }), [], {})).toBe('#6366f1')
  })

  it('returns google blue for non-tether source', () => {
    expect(resolveEventColor(makeEvent({ source: 'google_calendar', color: null }), [], {})).toBe('#4285f4')
  })
})
