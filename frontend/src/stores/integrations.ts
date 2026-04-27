import { defineStore } from 'pinia'
import { ref } from 'vue'
import { api } from '../lib/api'

export const useIntegrationsStore = defineStore('integrations', () => {
  const gcalConnected = ref(false)
  const loading = ref(false)
  const error = ref<string | null>(null)
  const lastSyncedAt = ref<string | null>(null)

  /**
   * Check Google Calendar connection status.
   * Uses GET /api/integrations/google/calendars as a proxy:
   * - 200 → connected
   * - 404 / 401 / network error → not connected
   */
  async function fetchGCalStatus() {
    loading.value = true
    error.value = null
    try {
      const resp = await api('/api/integrations/google/calendars')
      gcalConnected.value = resp.ok
    } catch {
      gcalConnected.value = false
      error.value = 'Could not reach server. Check your connection.'
    } finally {
      loading.value = false
    }
  }

  /**
   * Initiate Google Calendar OAuth flow.
   * Navigates the page to the backend OAuth redirect endpoint.
   */
  function connectGCal() {
    window.location.href = '/api/integrations/google/connect'
  }

  /**
   * Disconnect Google Calendar integration.
   * POST /api/integrations/google/disconnect — revokes tokens and deletes the row.
   */
  async function disconnectGCal() {
    loading.value = true
    error.value = null
    try {
      const resp = await api('/api/integrations/google/disconnect', { method: 'POST' })
      if (resp.ok) {
        gcalConnected.value = false
      }
    } catch {
      error.value = 'Failed to disconnect. Please try again.'
    } finally {
      loading.value = false
    }
  }

  /**
   * Trigger an explicit Google Calendar sync.
   * POST /api/integrations/google/sync — re-pulls calendar events.
   */
  async function syncNow() {
    loading.value = true
    error.value = null
    try {
      const resp = await api('/api/integrations/google/sync', { method: 'POST' })
      if (resp.ok) {
        lastSyncedAt.value = new Date().toISOString()
      } else {
        error.value = 'Sync failed. Please try again.'
      }
    } catch {
      error.value = 'Sync failed. Please try again.'
    } finally {
      loading.value = false
    }
  }

  return {
    gcalConnected,
    loading,
    error,
    lastSyncedAt,
    fetchGCalStatus,
    connectGCal,
    disconnectGCal,
    syncNow,
  }
})
