import type { CalendarEvent } from '../types/events'
import type { Milestone } from '../stores/milestones'
import type { ContextNode } from '../stores/context'

const DEFAULT_COLOR = '#6366f1'
const GOOGLE_COLOR = '#4285f4'

/**
 * Resolve an event's display color following the hierarchy:
 *   non-tether source → google blue
 *   event.color → that
 *   milestone owning the task → milestone.color
 *   context node matching event.context_subject by name → node.color
 *   else → default indigo
 */
export function resolveEventColor(
  event: CalendarEvent,
  milestones: Milestone[],
  contextNodes: Record<string, ContextNode>,
): string {
  if (event.source !== 'tether') return GOOGLE_COLOR

  if (event.color) return event.color

  if (event.task_id) {
    for (const m of milestones) {
      if (m.task_ids.includes(event.task_id) && m.color) return m.color
    }
  }

  if (event.context_subject) {
    const node = Object.values(contextNodes).find(n => n.name === event.context_subject)
    if (node?.color) return node.color
  }

  return DEFAULT_COLOR
}
