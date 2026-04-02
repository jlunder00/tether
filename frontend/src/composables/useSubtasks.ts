import { ref, watch } from 'vue'

export interface Subtask {
  id: number
  task_id: string
  text: string
  done: boolean
  position: number
}

export function useSubtasks(taskId: () => string) {
  const subtasks = ref<Subtask[]>([])
  const loading = ref(false)

  async function fetch() {
    loading.value = true
    const resp = await window.fetch(`/api/tasks/${taskId()}/subtasks`, { credentials: 'include' })
    subtasks.value = resp.ok ? await resp.json() : []
    loading.value = false
  }

  async function create(text: string) {
    const position = subtasks.value.length
    const resp = await window.fetch(`/api/tasks/${taskId()}/subtasks`, {
      method: 'POST', credentials: 'include',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ text, position }),
    })
    if (resp.ok) await fetch()
  }

  async function update(id: number, fields: Partial<Subtask>) {
    await window.fetch(`/api/tasks/${taskId()}/subtasks/${id}`, {
      method: 'PATCH', credentials: 'include',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(fields),
    })
    await fetch()
  }

  async function remove(id: number) {
    await window.fetch(`/api/tasks/${taskId()}/subtasks/${id}`, {
      method: 'DELETE', credentials: 'include',
    })
    await fetch()
  }

  async function reorder(idOrder: number[]) {
    await window.fetch(`/api/tasks/${taskId()}/subtasks/reorder`, {
      method: 'PUT', credentials: 'include',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ id_order: idOrder }),
    })
    await fetch()
  }

  watch(taskId, () => fetch(), { immediate: true })

  return { subtasks, loading, fetch, create, update, remove, reorder }
}
