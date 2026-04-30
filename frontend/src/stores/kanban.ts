import { defineStore } from 'pinia'
import { ref } from 'vue'
import { api } from '../lib/api'
import type { Task } from './plan'

export interface KanbanColumn {
  id: string
  name: string
  position: number
  color: string | null
  match_rules: Record<string, unknown>
  entry_rules: Record<string, unknown>
  created_by: string | null
}

export interface KanbanTask extends Task {
  plan_date: string | null
  anchor_id: string | null
}

export const useKanbanStore = defineStore('kanban', () => {
  const columns = ref<KanbanColumn[]>([])
  const allTasks = ref<KanbanTask[]>([])
  const loading = ref(false)
  const tasksLoading = ref(false)
  const error = ref<string | null>(null)

  async function fetchColumns() {
    loading.value = true
    error.value = null
    try {
      const resp = await api('/api/kanban/columns')
      if (!resp.ok) throw new Error(`Failed to load columns (HTTP ${resp.status})`)
      const data = await resp.json()
      if (Array.isArray(data)) columns.value = data
    } catch (e) {
      console.error('fetchKanbanColumns error:', e)
      error.value = e instanceof Error ? e.message : 'Failed to load kanban columns'
      columns.value = []
    } finally {
      loading.value = false
    }
  }

  async function fetchAllTasks() {
    tasksLoading.value = true
    try {
      const resp = await api('/api/tasks/all')
      if (!resp.ok) throw new Error(`${resp.status}`)
      allTasks.value = await resp.json()
    } catch (e) {
      console.error('fetchAllTasks error:', e)
    } finally {
      tasksLoading.value = false
    }
  }

  /**
   * Merge a partial PATCH into the local task copy so views holding
   * `allTasks` re-render immediately after a detail-panel edit.
   * No-op if the task isn't in the local list (e.g. kanban not loaded yet).
   */
  function applyTaskPatch(taskId: string, patch: Partial<KanbanTask>) {
    const i = allTasks.value.findIndex(t => t.id === taskId)
    if (i === -1) return
    allTasks.value[i] = { ...allTasks.value[i], ...patch }
  }

  return {
    columns,
    allTasks,
    loading,
    tasksLoading,
    error,
    fetchColumns,
    fetchAllTasks,
    applyTaskPatch,
  }
})
