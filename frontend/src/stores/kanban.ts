import { defineStore } from 'pinia'
import { ref } from 'vue'
import { api } from '../lib/api'
import type { Task, TaskStatus } from './plan'

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

  const VALID_STATUSES: ReadonlySet<string> = new Set(['pending', 'in_progress', 'done', 'skipped', 'blocked'])
  // Tracks in-flight drops per taskId — prevents duplicate API calls if user
  // drops the same card twice before the first request resolves.
  const pendingDrops = new Set<string>()

  /**
   * Move a task into a kanban column by applying the column's entry_rules.
   * Handles optimistic update + revert on failure.
   * Previously lived in KanbanView.onTaskDrop — moved here so views never
   * call api() directly for task mutations.
   */
  async function moveTaskToColumn(taskId: string, columnId: string): Promise<void> {
    if (pendingDrops.has(taskId)) return

    const column = columns.value.find(c => c.id === columnId)
    if (!column) return

    const task = allTasks.value.find(t => t.id === taskId)
    if (!task) return

    const rules = column.entry_rules
    const setStatus = rules['set_status']
    if (typeof setStatus !== 'string') return
    if (!VALID_STATUSES.has(setStatus)) return

    const patch: Record<string, unknown> = {}
    if (task.status !== setStatus) patch.status = setStatus
    if (rules['prompt_schedule'] && !task.plan_date) {
      patch.plan_date = new Date().toISOString().slice(0, 10)
    }
    if (rules['unschedule'] && task.plan_date) {
      patch.plan_date = null
      patch.anchor_id = null
    }

    if (!Object.keys(patch).length) return

    // Optimistic update — reflect change immediately in the UI
    const oldStatus = task.status
    const oldPlanDate = task.plan_date
    if (patch.status) task.status = patch.status as TaskStatus
    if ('plan_date' in patch) task.plan_date = patch.plan_date as string | null
    pendingDrops.add(taskId)

    try {
      const resp = await api(`/api/tasks/${taskId}`, {
        method: 'PATCH',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(patch),
      })
      if (!resp.ok) throw new Error(`PATCH failed: ${resp.status}`)
    } catch (e) {
      console.error('Failed to update task:', e)
      task.status = oldStatus
      task.plan_date = oldPlanDate
      await fetchAllTasks()
    } finally {
      pendingDrops.delete(taskId)
    }
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
    moveTaskToColumn,
  }
})
