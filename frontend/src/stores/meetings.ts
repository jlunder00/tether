import { defineStore } from 'pinia'
import { ref, computed } from 'vue'
import { api } from '../lib/api'
import type { MeetingRequest, MeetingRequestBody, MeetingStatus } from '../types/meetings'

export const useMeetingsStore = defineStore('meetings', () => {
  const meetings = ref<MeetingRequest[]>([])
  const loading = ref(false)
  const error = ref<string | null>(null)

  const openMeetings = computed(() =>
    meetings.value.filter(m => m.status === 'open'),
  )

  const pendingRequestIds = computed(() =>
    meetings.value.filter(m => m.status === 'open').map(m => m.id),
  )

  async function fetchMeetings(status?: MeetingStatus | string) {
    loading.value = true
    error.value = null
    try {
      const url = status ? `/api/meetings?status=${status}` : '/api/meetings'
      const resp = await api(url, { credentials: 'include' })
      if (resp.ok) {
        meetings.value = await resp.json()
      } else {
        error.value = 'Failed to load meetings.'
      }
    } catch {
      error.value = 'Could not reach server.'
    } finally {
      loading.value = false
    }
  }

  async function requestMeeting(body: MeetingRequestBody) {
    loading.value = true
    error.value = null
    try {
      const resp = await api('/api/meetings/request', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(body),
      })
      if (resp.ok) {
        const result = await resp.json()
        // Add a minimal stub meeting record so computed properties reflect the new request
        const stub: MeetingRequest = {
          id: result.id,
          initiator_id: '',
          target_ids: [],
          duration_minutes: body.duration_minutes,
          context: body.context ?? null,
          status: result.status,
          round: result.round,
          agreed_slot: null,
          created_at: new Date().toISOString(),
          updated_at: new Date().toISOString(),
        }
        meetings.value = [...meetings.value, stub]
      } else {
        const data = await resp.json().catch(() => ({}))
        error.value = (data as { detail?: string }).detail || 'Failed to send meeting request.'
      }
    } catch {
      error.value = 'Could not reach server.'
    } finally {
      loading.value = false
    }
  }

  async function cancelMeeting(meetingId: number) {
    loading.value = true
    error.value = null
    try {
      const resp = await api(`/api/meetings/${meetingId}/cancel`, { method: 'POST' })
      if (resp.ok) {
        const result = await resp.json()
        meetings.value = meetings.value.map(m =>
          m.id === meetingId ? { ...m, status: result.status } : m,
        )
      } else {
        error.value = 'Failed to cancel meeting.'
      }
    } catch {
      error.value = 'Could not reach server.'
    } finally {
      loading.value = false
    }
  }

  return {
    meetings,
    loading,
    error,
    openMeetings,
    pendingRequestIds,
    fetchMeetings,
    requestMeeting,
    cancelMeeting,
  }
})
