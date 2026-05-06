import { defineStore } from 'pinia'
import { ref } from 'vue'
import { api } from '../lib/api'

export interface ImportResult {
  imported: number
  updated: number
  skipped: number
  errors: { uid: string; error: string }[]
  total_events: number
  warning?: string
}

function errorMessageForStatus(status: number, detail?: string): string {
  if (status === 413) return 'File is too large (max 5 MB).'
  if (status === 422) return detail ?? 'Invalid ICS file or URL.'
  if (status === 502) return 'Could not fetch the remote calendar — server or URL may be unavailable.'
  return detail ?? 'Import failed. Please try again.'
}

export const useICalStore = defineStore('ical', () => {
  const importing = ref(false)
  const lastResult = ref<ImportResult | null>(null)
  const lastError = ref<string | null>(null)

  /**
   * Import events from a local .ics file.
   * POST /api/ical/import (multipart/form-data)
   */
  async function importFile(file: File, skipAllDay: boolean): Promise<ImportResult | null> {
    importing.value = true
    lastError.value = null

    try {
      const body = new FormData()
      body.append('file', file)

      const url = skipAllDay ? '/api/ical/import?skip_all_day=true' : '/api/ical/import'
      const resp = await api(url, { method: 'POST', body })

      if (!resp.ok) {
        const data = await resp.json().catch(() => ({})) as { detail?: string }
        lastError.value = errorMessageForStatus(resp.status, data.detail)
        lastResult.value = null
        return null
      }

      const result: ImportResult = await resp.json()
      lastResult.value = result
      return result
    } catch {
      lastError.value = 'Network error. Check your connection and try again.'
      lastResult.value = null
      return null
    } finally {
      importing.value = false
    }
  }

  /**
   * Import events from a subscription URL (webcal:// or https://).
   * POST /api/ical/import (application/json)
   */
  async function importUrl(feedUrl: string, skipAllDay: boolean): Promise<ImportResult | null> {
    importing.value = true
    lastError.value = null

    try {
      const url = skipAllDay ? '/api/ical/import?skip_all_day=true' : '/api/ical/import'
      const resp = await api(url, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ url: feedUrl }),
      })

      if (!resp.ok) {
        const data = await resp.json().catch(() => ({})) as { detail?: string }
        lastError.value = errorMessageForStatus(resp.status, data.detail)
        lastResult.value = null
        return null
      }

      const result: ImportResult = await resp.json()
      lastResult.value = result
      return result
    } catch {
      lastError.value = 'Network error. Check your connection and try again.'
      lastResult.value = null
      return null
    } finally {
      importing.value = false
    }
  }

  /** Reset result and error state (e.g. when the user switches modes or dismisses). */
  function clearResult() {
    lastResult.value = null
    lastError.value = null
  }

  return { importing, lastResult, lastError, importFile, importUrl, clearResult }
})
