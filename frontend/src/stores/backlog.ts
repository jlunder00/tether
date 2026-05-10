import { defineStore } from 'pinia'
import { ref } from 'vue'
import { api } from '../lib/api'
import type { Task } from './plan'

export const useBacklogStore = defineStore('backlog', () => {
  const tasks = ref<Task[]>([])
  const loading = ref(false)

  async function fetchTasks() {
    loading.value = true
    try {
      const resp = await api('/api/tasks/unscheduled')
      if (!resp.ok) throw new Error(`${resp.status}`)
      tasks.value = await resp.json()
    } catch (e) {
      console.error('fetchBacklog error:', e)
      tasks.value = []
    } finally {
      loading.value = false
    }
  }

  async function createTask(
    text: string,
    opts: { description?: string; status?: string; date?: string; context_subject?: string; milestone_id?: string } = {},
  ): Promise<Task> {
    const resp = await api('/api/tasks/unscheduled', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ text, ...opts }),
    })
    if (!resp.ok) throw new Error(`${resp.status}`)
    const task = await resp.json()
    tasks.value = [...tasks.value, task]
    return task
  }

  return { tasks, loading, fetchTasks, createTask }
})
