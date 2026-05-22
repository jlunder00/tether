import { defineStore } from 'pinia'
import { ref } from 'vue'
import { api } from '../lib/api'

export interface BeaconSuppression {
  id: string
  scope_key: string
  reason: string | null
  source: 'user_rejection' | 'beacon_decision' | 'system'
  created_at: string
  expires_at: string | null
}

// Store for Beacon suppression history (GET /api/beacon/suppressions).
// Endpoint is not yet implemented — handles 404 gracefully by returning empty array.
// This store is premium-only; caller is responsible for not mounting if is_paid=false.
export const useSuppressionsStore = defineStore('suppressions', () => {
  const suppressions = ref<BeaconSuppression[]>([])
  const loading = ref(false)
  const error = ref<string | null>(null)

  async function fetch(): Promise<void> {
    loading.value = true
    error.value = null
    try {
      const res = await api('/api/beacon/suppressions')
      if (res.status === 404) {
        // Backend endpoint not yet implemented — return empty array gracefully.
        suppressions.value = []
        return
      }
      if (!res.ok) throw new Error(`HTTP ${res.status}`)
      suppressions.value = await res.json()
    } catch (e) {
      error.value = String(e)
      suppressions.value = []
    } finally {
      loading.value = false
    }
  }

  return { suppressions, loading, error, fetch }
})
