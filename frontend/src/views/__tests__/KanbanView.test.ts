import { describe, it, expect, vi, beforeEach, type Mock } from 'vitest'
import type { TaskStatus } from '../../stores/plan'

// Test the onTaskDrop logic in isolation.
// KanbanView is complex to mount (router, stores, API), so we test
// the handler logic directly with a portable helper that mirrors
// the implementation. Field coverage is partial (only id + status).

interface MockTask {
  id: string
  status: TaskStatus
}

interface MockColumn {
  id: string
  entry_rules: Record<string, unknown>
}

const VALID_STATUSES: Set<string> = new Set(['pending', 'in_progress', 'done', 'skipped', 'blocked'])

function createTaskDropHandler(
  allTasks: { value: MockTask[] },
  columns: MockColumn[],
  patchFn: (taskId: string, status: string) => Promise<{ ok: boolean }>,
  refetchFn: () => Promise<void>,
) {
  const pendingDrops = new Set<string>()

  return async function onTaskDrop(taskId: string, columnId: string) {
    if (pendingDrops.has(taskId)) return

    const column = columns.find(c => c.id === columnId)
    if (!column) return

    const task = allTasks.value.find(t => t.id === taskId)
    if (!task) return

    const setStatus = column.entry_rules['set_status']
    if (typeof setStatus !== 'string') return
    if (!VALID_STATUSES.has(setStatus)) return

    if (task.status === setStatus) return

    const oldStatus = task.status
    task.status = setStatus as TaskStatus
    pendingDrops.add(taskId)

    try {
      const resp = await patchFn(taskId, setStatus)
      if (!resp.ok) throw new Error('PATCH failed')
    } catch {
      task.status = oldStatus
      await refetchFn()
    } finally {
      pendingDrops.delete(taskId)
    }
  }
}

describe('onTaskDrop logic', () => {
  const columns: MockColumn[] = [
    { id: 'col_backlog', entry_rules: {} },
    { id: 'col_pending', entry_rules: { set_status: 'pending', prompt_schedule: true } },
    { id: 'col_in_progress', entry_rules: { set_status: 'in_progress' } },
    { id: 'col_done', entry_rules: { set_status: 'done' } },
    { id: 'col_invalid', entry_rules: { set_status: 'nonexistent_status' } },
  ]

  let allTasks: { value: MockTask[] }
  let patchFn: Mock<(taskId: string, status: string) => Promise<{ ok: boolean }>>
  let refetchFn: Mock<() => Promise<void>>
  let onTaskDrop: (taskId: string, columnId: string) => Promise<void>

  beforeEach(() => {
    allTasks = { value: [{ id: 'task-1', status: 'pending' }] }
    patchFn = vi.fn(() => Promise.resolve({ ok: true }))
    refetchFn = vi.fn(() => Promise.resolve())
    onTaskDrop = createTaskDropHandler(allTasks, columns, patchFn, refetchFn)
  })

  it('updates task status and calls PATCH on cross-column drop', async () => {
    await onTaskDrop('task-1', 'col_done')
    expect(allTasks.value[0].status).toBe('done')
    expect(patchFn).toHaveBeenCalledWith('task-1', 'done')
  })

  it('is a no-op when dropping on same-status column', async () => {
    await onTaskDrop('task-1', 'col_pending')
    expect(patchFn).not.toHaveBeenCalled()
  })

  it('is a no-op when dropping on column with no set_status (Backlog)', async () => {
    await onTaskDrop('task-1', 'col_backlog')
    expect(patchFn).not.toHaveBeenCalled()
  })

  it('is a no-op when column has invalid set_status value', async () => {
    await onTaskDrop('task-1', 'col_invalid')
    expect(patchFn).not.toHaveBeenCalled()
  })

  it('reverts status and refetches on PATCH failure', async () => {
    patchFn.mockRejectedValueOnce(new Error('network'))
    await onTaskDrop('task-1', 'col_done')
    expect(allTasks.value[0].status).toBe('pending')
    expect(refetchFn).toHaveBeenCalled()
  })

  it('reverts status on non-ok response', async () => {
    patchFn.mockResolvedValueOnce({ ok: false })
    await onTaskDrop('task-1', 'col_done')
    expect(allTasks.value[0].status).toBe('pending')
    expect(refetchFn).toHaveBeenCalled()
  })

  it('is a no-op for unknown task id', async () => {
    await onTaskDrop('nonexistent', 'col_done')
    expect(patchFn).not.toHaveBeenCalled()
  })

  it('is a no-op for unknown column id', async () => {
    await onTaskDrop('task-1', 'nonexistent')
    expect(patchFn).not.toHaveBeenCalled()
  })

  it('ignores concurrent drops on the same task (in-flight guard)', async () => {
    // Make patchFn slow so we can fire a second drop while first is in-flight
    let resolvePatch!: () => void
    patchFn.mockImplementationOnce(() => new Promise(resolve => {
      resolvePatch = () => resolve({ ok: true })
    }))

    const p1 = onTaskDrop('task-1', 'col_done')
    // Task is now in-flight — second drop should be ignored
    await onTaskDrop('task-1', 'col_in_progress')
    expect(patchFn).toHaveBeenCalledTimes(1)
    expect(patchFn).toHaveBeenCalledWith('task-1', 'done')

    // Resolve first drop
    resolvePatch()
    await p1
    expect(allTasks.value[0].status).toBe('done')
  })
})
