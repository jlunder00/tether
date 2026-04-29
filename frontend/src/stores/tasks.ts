import { defineStore } from 'pinia'
import { api } from '../lib/api'
import type { RecurrenceEditScope } from '../types/recurrence'

/**
 * Thin store for task-level mutations that don't belong in plan or backlog.
 *
 * - setTaskRrule: PATCH /api/tasks/:id/rrule — set or clear rrule on an anchor task
 * - deleteTask: DELETE /api/tasks/:id — scope-aware delete (supports recurring masters)
 */
export const useTasksStore = defineStore('tasks', () => {
  /**
   * Set or clear the rrule on an anchor task.
   * @param taskId  UUID of the task to update
   * @param rrule   RRULE string (e.g. "FREQ=WEEKLY;BYDAY=MO") or null to clear
   */
  async function setTaskRrule(taskId: string, rrule: string | null): Promise<void> {
    await api(`/api/tasks/${taskId}/rrule`, {
      method: 'PATCH',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ rrule }),
    })
  }

  /**
   * Delete a task, optionally scoped for recurring task masters.
   * @param taskId       UUID of the task (or occurrence) to delete
   * @param scope        Recurrence scope: 'this' | 'this_and_future' | 'all'.
   *                     Omit for non-recurring tasks.
   * @param originalDate YYYY-MM-DD date of the occurrence being deleted.
   *                     Required when scope is 'this' or 'this_and_future'.
   */
  async function deleteTask(
    taskId: string,
    scope?: RecurrenceEditScope | 'this_and_future',
    originalDate?: string,
  ): Promise<void> {
    const params = new URLSearchParams()
    if (scope) params.set('scope', scope)
    if (originalDate && scope !== 'all') params.set('original_date', originalDate)
    const query = params.toString() ? `?${params.toString()}` : ''
    await api(`/api/tasks/${taskId}${query}`, { method: 'DELETE' })
  }

  return { setTaskRrule, deleteTask }
})
