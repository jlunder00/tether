import { defineStore } from 'pinia'
import { ref } from 'vue'

export interface ContextEntry { subject: string; body: string; updated_at: string }

export const useContextStore = defineStore('context', () => {
  const entries = ref<ContextEntry[]>([])

  async function fetchEntries() {
    const resp = await fetch('/api/context')
    entries.value = await resp.json()
  }

  async function saveEntry(subject: string, body: string) {
    await fetch(`/api/context/${encodeURIComponent(subject)}`, {
      method: 'PUT',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ body }),
    })
    await fetchEntries()
  }

  async function deleteEntry(subject: string) {
    await fetch(`/api/context/${encodeURIComponent(subject)}`, { method: 'DELETE' })
    await fetchEntries()
  }

  async function renameEntry(oldSubject: string, newSubject: string) {
    await fetch(`/api/context/${encodeURIComponent(oldSubject)}/rename`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ new_subject: newSubject }),
    })
    await fetchEntries()
  }

  return { entries, fetchEntries, saveEntry, deleteEntry, renameEntry }
})
