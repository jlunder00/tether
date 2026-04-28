import { defineStore } from 'pinia'
import { ref } from 'vue'
import { api } from '../lib/api'
import type { CalendarEvent } from '../types/events'

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
   * POST /api/events — not yet implemented; returns a local optimistic event.
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
      rrule: null,
      context_subject: null,
    }
    events.value.push(optimistic)
    return optimistic
  }

  /**
   * Move an existing event to a new time slot (drag-to-reposition).
   * PATCH /api/events/:id — not yet implemented; updates optimistically.
   */
  async function moveEvent(eventId: string, startTime: string, endTime: string): Promise<void> {
    const ev = events.value.find(e => e.id === eventId)
    if (!ev) return
    // Optimistic update
    ev.start_time = startTime
    ev.end_time = endTime
    try {
      await api(`/api/events/${eventId}`, {
        method: 'PATCH',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ start_time: startTime, end_time: endTime }),
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
   * Demote a calendar event back to a plain task (removes time constraint).
   * DELETE /api/events/:id/time-constraint
   */
  async function demoteEvent(eventId: string) {
    try {
      await api(`/api/events/${eventId}/time-constraint`, { method: 'DELETE' })
    } catch { /* ignore */ }
    events.value = events.value.filter(e => e.id !== eventId)
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

  return { events, loading, error, fetchEvents, promoteTask, createTaskAndPromote, moveEvent, demoteEvent, removeEventsForTask, setRecurrence }
})
