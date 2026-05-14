import { defineStore } from 'pinia'
import { ref } from 'vue'
import { api } from '../lib/api'
import type { CalendarEvent } from '../types/events'
import type { RecurrenceEditScope } from '../types/recurrence'
import { usePlanStore } from './plan'

export const useEventStore = defineStore('events', () => {
  const events = ref<CalendarEvent[]>([])
  const loading = ref(false)
  const error = ref<string | null>(null)

  /**
   * Fetch events for a date range.
   * Backend GET /api/events is not yet implemented — falls back to an empty
   * list on any failure so the calendar still renders.
   */
  async function fetchEvents(start: string, end: string) {
    loading.value = true
    error.value = null
    try {
      const resp = await api(`/api/events?start=${start}&end=${end}`)
      events.value = resp.ok ? await resp.json() : []
    } catch {
      events.value = []
    } finally {
      loading.value = false
    }
  }

  /**
   * Promote a task to a calendar event (sets start/end time).
   * POST /api/events — creates a calendar event with the given time range.
   */
  async function promoteTask(taskId: string, startTime: string, endTime: string, title: string): Promise<CalendarEvent | null> {
    try {
      const resp = await api('/api/events', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ task_id: taskId, start_time: startTime, end_time: endTime, title }),
      })
      if (resp.ok) {
        const event: CalendarEvent = await resp.json()
        events.value.push(event)
        return event
      }
    } catch { /* fall through */ }
    // Optimistic local insert until backend ships
    const optimistic: CalendarEvent = {
      id: crypto.randomUUID?.() ?? (Math.random().toString(36).slice(2) + Date.now().toString(36)),
      title,
      start_time: startTime,
      end_time: endTime,
      source: 'tether',
      external_id: null,
      task_id: taskId,
      anchor_id: null,
      color: null,
      is_recurring: false,
      is_occurrence: false,
      is_all_day: false,
      rrule: null,
      context_subject: null,
    }
    events.value.push(optimistic)
    return optimistic
  }

  /**
   * Move an existing event to a new time slot (drag-to-reposition).
   * For recurring occurrences, scope chooses whether the move applies to just
   * this occurrence ('this'), this and all future ('this_and_future'), or the
   * whole series ('all'). When scope is provided, the original_start_time of
   * the occurrence must accompany it so the backend can identify which
   * instance to split.
   */
  async function moveEvent(
    eventId: string,
    startTime: string,
    endTime: string,
    scope?: 'this' | 'this_and_future' | 'all',
    originalStartTime?: string,
  ): Promise<void> {
    const ev = events.value.find(e => e.id === eventId)
    if (!ev) return
    // Optimistic update
    ev.start_time = startTime
    ev.end_time = endTime
    const body: Record<string, unknown> = { start_time: startTime, end_time: endTime }
    if (scope) {
      body.scope = scope
      if (originalStartTime) body.original_start_time = originalStartTime
    }
    try {
      await api(`/api/events/${eventId}`, {
        method: 'PATCH',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(body),
      })
    } catch { /* ignore — optimistic update stays */ }
  }

  /**
   * Drag-to-create: creates a real unscheduled task then immediately promotes it
   * to a calendar event. Returns the new task's ID so the caller can open its
   * detail panel. Returns null if either step fails.
   */
  async function createTaskAndPromote(startTime: string, endTime: string): Promise<string | null> {
    // Step 1 — create a real unscheduled task
    let taskId: string
    try {
      const taskResp = await api('/api/tasks/unscheduled', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ text: 'New Event', status: 'pending' }),
      })
      if (!taskResp.ok) return null
      const task = await taskResp.json()
      taskId = task.id
    } catch {
      return null
    }

    // Step 2 — promote the task to a calendar event
    try {
      const eventResp = await api('/api/events', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ task_id: taskId, start_time: startTime, end_time: endTime }),
      })
      if (eventResp.ok) {
        const event: CalendarEvent = await eventResp.json()
        events.value.push(event)
      }
    } catch { /* event promotion failed — task exists but isn't on calendar yet */ }

    return taskId
  }

  /**
   * Demote a calendar event to a plain anchor-bound task.
   * Finds the linked task_id and PATCHes it with null times + anchorId + planDate.
   *
   * Optimistic (two-phase):
   *   1. Remove the event from events.value immediately — calendar hides it at once.
   *   2. Insert a stub task into planStore SYNCHRONOUSLY (before any await) so the
   *      task appears in the anchor the moment the event disappears. The stub carries
   *      the real task id, so fetchPlanRange's subsequent write reconciles by id.
   *   3. Await the PATCH.
   *   4. On any failure (thrown error OR non-ok response): remove the stub via
   *      planStore.removeTaskFromPlans so the UI doesn't show stale phantom data.
   *      We check resp.ok explicitly (not just catch) because a non-ok response
   *      is a real failure — a stuck stub is more disorienting than a missing event.
   */
  async function demoteEvent(eventId: string, anchorId: string, planDate: string): Promise<void> {
    const ev = events.value.find(e => e.id === eventId)
    if (!ev?.task_id) {
      console.warn('Cannot demote event with no task_id — skipping')
      return
    }

    // Step 1 — optimistically remove event from calendar
    events.value = events.value.filter(e => e.id !== eventId)

    // Step 2 — optimistically insert stub task into plan caches (synchronous, before any await)
    const planStore = usePlanStore()
    const stubTask = {
      id: ev.task_id,
      text: ev.title,
      description: null,
      status: 'pending' as const,
      position: 0,
      followup_config: null,
      blocks: [] as string[],
      blocked_by: [] as string[],
      context_subject: ev.context_subject,
      context_node_id: null,
      start_time: null,
      end_time: null,
      anchor_id: anchorId,
      plan_date: planDate,
      rrule: null,
      is_recurring_master: false,
      color: ev.color,
      motif: null,
    }
    planStore.insertStubTask(planDate, anchorId, stubTask)

    // Step 3 — PATCH the task on the server
    try {
      const resp = await api(`/api/tasks/${ev.task_id}`, {
        method: 'PATCH',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ start_time: null, end_time: null, anchor_id: anchorId, plan_date: planDate }),
      })
      // Step 4a — non-ok response: roll back stub
      if (!resp.ok) {
        planStore.removeTaskFromPlans(ev.task_id)
      }
    } catch {
      // Step 4b — network error: roll back stub
      planStore.removeTaskFromPlans(ev.task_id)
    }
  }

  /**
   * Delete a calendar event, optionally targeting a specific occurrence scope.
   * When scope is provided, original_start_time identifies which instance.
   */
  async function deleteEvent(
    eventId: string,
    scope?: 'this' | 'this_and_future' | 'all',
    originalStartTime?: string,
  ): Promise<void> {
    events.value = events.value.filter(e => e.id !== eventId)
    try {
      const params = new URLSearchParams()
      if (scope) params.set('scope', scope)
      if (originalStartTime) params.set('original_start_time', originalStartTime)
      const qs = params.toString() ? `?${params.toString()}` : ''
      await api(`/api/events/${eventId}${qs}`, { method: 'DELETE' })
    } catch { /* ignore — optimistic update stays */ }
  }

  /**
   * Remove all local event entries for a given task id.
   * Called after task deletion so the calendar grid updates immediately
   * without waiting for a full re-fetch.
   */
  function removeEventsForTask(taskId: string) {
    events.value = events.value.filter(e => e.task_id !== taskId)
  }

  /**
   * Update the color of a calendar event. Pass null to reset to default.
   * PATCH /api/events/:id with { color } — updates optimistically.
   *
   * For recurring events the caller must have already obtained user consent via
   * RecurrenceEditDialog and should pass:
   *   scope            — 'this' | 'this_and_future' | 'all'
   *   originalStartTime — required when scope !== 'all' and the event is an
   *                        occurrence (is_occurrence: true), so the backend can
   *                        identify which instance to split.
   */
  async function updateEventColor(
    eventId: string,
    color: string | null,
    scope?: RecurrenceEditScope,
    originalStartTime?: string,
  ): Promise<void> {
    const ev = events.value.find(e => e.id === eventId)
    if (!ev) return
    // Optimistic update — always safe because the caller has already confirmed
    // (recurring path gates this call behind RecurrenceEditDialog).
    ev.color = color
    const body: Record<string, unknown> = { color }
    if (scope) {
      body.scope = scope
      if (originalStartTime) body.original_start_time = originalStartTime
    }
    try {
      await api(`/api/events/${eventId}`, {
        method: 'PATCH',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(body),
      })
    } catch { /* ignore — optimistic update stays */ }
  }

  /**
   * Set or clear the recurrence rule for a calendar event.
   * Pass null to remove the recurrence entirely.
   * PATCH /api/events/:id with { rrule } — updates optimistically.
   */
  async function setRecurrence(eventId: string, rrule: string | null): Promise<void> {
    const ev = events.value.find(e => e.id === eventId)
    if (!ev) return
    // Occurrences cannot carry their own rrule — only the master can.
    if (ev.is_occurrence) return
    // Optimistic update
    ev.rrule = rrule
    ev.is_recurring = rrule !== null
    try {
      await api(`/api/events/${eventId}`, {
        method: 'PATCH',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ rrule }),
      })
    } catch { /* ignore — optimistic update stays */ }
  }

  /**
   * PATCH an event with scope support (single / this_and_future / all).
   * Used by CalendarView.onRecurrenceScopeConfirm (event-edit branch).
   */
  async function patchEvent(
    eventId: string,
    patch: Record<string, unknown>,
    scope: RecurrenceEditScope,
    originalStartTime?: string,
  ): Promise<void> {
    await api(`/api/events/${eventId}`, {
      method: 'PATCH',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ ...patch, scope, original_start_time: originalStartTime }),
    })
  }

  return { events, loading, error, fetchEvents, promoteTask, createTaskAndPromote, moveEvent, demoteEvent, deleteEvent, removeEventsForTask, setRecurrence, updateEventColor, patchEvent }
})
