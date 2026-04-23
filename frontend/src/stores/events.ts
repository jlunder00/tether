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
      id: crypto.randomUUID(),
      title,
      start_time: startTime,
      end_time: endTime,
      source: 'tether',
      external_id: null,
      task_id: taskId,
      anchor_id: null,
      color: null,
    }
    events.value.push(optimistic)
    return optimistic
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

  return { events, loading, error, fetchEvents, promoteTask, demoteEvent }
})
