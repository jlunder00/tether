import { ref, watch } from 'vue'
import { api } from '../lib/api'

export function useTaskContexts(taskId: () => string) {
  const contexts = ref<string[]>([])

  async function fetch() {
    const resp = await api(`/api/tasks/${taskId()}/contexts`)
    contexts.value = resp.ok ? await resp.json() : []
  }

  async function link(subject: string) {
    await api(`/api/tasks/${taskId()}/contexts`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ subject }),
    })
    await fetch()
  }

  async function unlink(subject: string) {
    await api(`/api/tasks/${taskId()}/contexts/${encodeURIComponent(subject)}`, {
      method: 'DELETE',
    })
    await fetch()
  }

  watch(taskId, () => fetch(), { immediate: true })

  return { contexts, fetch, link, unlink }
}
