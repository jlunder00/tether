/**
 * KanbanStore — moveTaskToColumn action
 *
 * The PATCH API call was previously in KanbanView.onTaskDrop. Track 3 moves it
 * into a store action so views never call api() directly for task status changes.
 */
import { describe, it, expect, vi, beforeEach } from 'vitest'
import { createPinia, setActivePinia } from 'pinia'
import { api } from '../../lib/api'

vi.mock('../../lib/api', () => ({
  api: vi.fn(() => Promise.resolve({ ok: true, json: () => Promise.resolve({}) })),
}))

const mockApi = vi.mocked(api)

function makeTask(overrides: Record<string, unknown> = {}) {
  return {
    id: 'task-1',
    text: 'Test task',
    status: 'pending',
    position: 0,
    description: null,
    followup_config: null,
    blocks: [],
    blocked_by: [],
    context_subject: null,
    context_node_id: null,
    plan_date: null,
    anchor_id: null,
    ...overrides,
  }
}

function makeColumn(overrides: Record<string, unknown> = {}) {
  return {
    id: 'col-done',
    name: 'Done',
    position: 1,
    color: null,
    match_rules: { status: 'done' },
    entry_rules: { set_status: 'done' },
    created_by: null,
    ...overrides,
  }
}

describe('useKanbanStore — moveTaskToColumn', () => {
  beforeEach(() => {
    setActivePinia(createPinia())
    vi.clearAllMocks()
  })

  async function setup(taskOverrides: Record<string, unknown> = {}, columnOverrides: Record<string, unknown> = {}) {
    const { useKanbanStore } = await import('../kanban')
    const store = useKanbanStore()
    const task = makeTask(taskOverrides)
    const column = makeColumn(columnOverrides)
    store.allTasks.push(task as any)
    store.columns.push(column as any)
    return { store, task, column }
  }

  it('PATCHes /api/tasks/:id with status from column entry_rules.set_status', async () => {
    const { store } = await setup()

    await store.moveTaskToColumn('task-1', 'col-done')

    expect(mockApi).toHaveBeenCalledOnce()
    const [url, opts] = mockApi.mock.calls[0]
    expect(url).toBe('/api/tasks/task-1')
    expect(opts?.method).toBe('PATCH')
    const body = JSON.parse(opts?.body as string)
    expect(body.status).toBe('done')
  })

  it('adds plan_date=today when column prompt_schedule is set and task has no plan_date', async () => {
    const today = new Date().toISOString().slice(0, 10)
    const { store } = await setup(
      { plan_date: null },
      { entry_rules: { set_status: 'in_progress', prompt_schedule: true } },
    )

    await store.moveTaskToColumn('task-1', 'col-done')

    const body = JSON.parse(mockApi.mock.calls[0][1]?.body as string)
    expect(body.plan_date).toBe(today)
  })

  it('sets plan_date=null and anchor_id=null when column unschedule rule is true', async () => {
    const { store } = await setup(
      { plan_date: '2026-05-01', anchor_id: 'morning' },
      { entry_rules: { set_status: 'done', unschedule: true } },
    )

    await store.moveTaskToColumn('task-1', 'col-done')

    const body = JSON.parse(mockApi.mock.calls[0][1]?.body as string)
    expect(body.plan_date).toBeNull()
    expect(body.anchor_id).toBeNull()
  })

  it('applies optimistic status update before API call resolves', async () => {
    let resolveApi!: () => void
    mockApi.mockImplementationOnce(
      () => new Promise(res => { resolveApi = () => res({ ok: true, json: () => Promise.resolve({}) } as any) })
    )
    const { store, task } = await setup()

    const movePromise = store.moveTaskToColumn('task-1', 'col-done')
    // Status should already be updated before we resolve the API call
    expect(task.status).toBe('done')

    resolveApi()
    await movePromise
  })

  it('reverts optimistic update and re-fetches on API error', async () => {
    mockApi
      .mockRejectedValueOnce(new Error('network error'))
      .mockResolvedValue({ ok: true, json: () => Promise.resolve([]) } as any)
    const { store, task } = await setup()

    await store.moveTaskToColumn('task-1', 'col-done')

    expect(task.status).toBe('pending')
    // fetchAllTasks was called to re-sync
    expect(mockApi).toHaveBeenCalledTimes(2)
  })

  it('is a no-op when the status already matches the column (empty patch)', async () => {
    const { store } = await setup({ status: 'done' })

    await store.moveTaskToColumn('task-1', 'col-done')

    expect(mockApi).not.toHaveBeenCalled()
  })

  it('is a no-op when column has no valid set_status entry rule', async () => {
    const { store } = await setup(
      {},
      { entry_rules: {} },
    )

    await store.moveTaskToColumn('task-1', 'col-done')

    expect(mockApi).not.toHaveBeenCalled()
  })

  it('ignores unknown status values not in VALID_STATUSES', async () => {
    const { store } = await setup(
      {},
      { entry_rules: { set_status: 'hacked_status' } },
    )

    await store.moveTaskToColumn('task-1', 'col-done')

    expect(mockApi).not.toHaveBeenCalled()
  })

  it('ignores a second concurrent drop for the same taskId while first is in-flight', async () => {
    let resolveApi!: () => void
    mockApi.mockImplementationOnce(
      () => new Promise(res => { resolveApi = () => res({ ok: true, json: () => Promise.resolve({}) } as any) })
    )
    const { store } = await setup()

    // First call — in flight
    const first = store.moveTaskToColumn('task-1', 'col-done')
    // Second call — should be ignored because task-1 is pending
    await store.moveTaskToColumn('task-1', 'col-done')

    expect(mockApi).toHaveBeenCalledTimes(1)
    resolveApi()
    await first
  })
})
