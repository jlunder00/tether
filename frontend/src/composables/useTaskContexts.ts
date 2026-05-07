import { ref, watch } from 'vue'
import { api } from '../lib/api'

export function useTaskContexts(taskId: () => string) {
  const contexts = ref<string[]>([])

  async function load() {
    const resp = await api(`/api/tasks/${taskId()}/contexts`)
    // API returns [] or [subject] (single-context model)
    contexts.value = resp.ok ? await resp.json() : []
  }

  async function link(subject: string) {
    // POST replaces existing context_subject
    await api(`/api/tasks/${taskId()}/contexts`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ subject }),
    })
    await load()
  }

  async function unlink(subject: string) {
    // DELETE clears context_subject (subject param kept for API compat)
    await api(`/api/tasks/${taskId()}/contexts/${encodeURIComponent(subject)}`, {
      method: 'DELETE',
    })
    await load()
  }

  watch(taskId, () => load(), { immediate: true })

  return { contexts, load, link, unlink }
}
