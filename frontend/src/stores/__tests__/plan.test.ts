/**
 * plan store — patchTaskFields + moveTask actions
 *
 * Verifies that patchTaskFields:
 *   1. PATCHes /api/tasks/:id with the given fields
 *   2. Applies an optimistic update to the in-memory plan
 *   3. Returns true on success, false on API error
 *
 * Verifies that moveTask:
 *   4. Removes task from in-memory plan even when toDate is not cached
 *   5. Inserts into toDate when it's in plans cache, even if fromDay is not the active plan
 */
import { describe, it, expect, vi, beforeEach } from 'vitest'
import { setActivePinia, createPinia } from 'pinia'

vi.mock('../../lib/api', () => ({
  api: vi.fn(() => Promise.resolve({ ok: true, json: async () => ({}) })),
}))

describe('usePlanStore – patchTaskFields', () => {
  beforeEach(() => {
    setActivePinia(createPinia())
    vi.clearAllMocks()
  })

  it('PATCHes /api/tasks/:id with the provided fields', async () => {
    const { api } = await import('../../lib/api')
    vi.mocked(api).mockResolvedValueOnce({ ok: true, json: async () => ({}) } as any)
    const { usePlanStore } = await import('../plan')
    const store = usePlanStore()

    await store.patchTaskFields('task-abc', { status: 'done' })

    expect(vi.mocked(api)).toHaveBeenCalledWith(
      '/api/tasks/task-abc',
      expect.objectContaining({
        method: 'PATCH',
        body: JSON.stringify({ status: 'done' }),
      }),
    )
  })

  it('applies optimistic update to matching task in plan', async () => {
    const { api } = await import('../../lib/api')
    vi.mocked(api).mockResolvedValueOnce({ ok: true, json: async () => ({}) } as any)
    const { usePlanStore } = await import('../plan')
    const store = usePlanStore()

    // Seed plan state with a task
    store.plan = {
      date: '2026-05-01',
      anchors: {
        morning: {
          tasks: [{ id: 'task-abc', text: 'Write tests', status: 'pending', position: 0 } as any],
          notes: '',
        },
      },
    } as any

    await store.patchTaskFields('task-abc', { status: 'done', motif: 'focus' })

    const task = store.plan!.anchors.morning.tasks[0]
    expect(task.status).toBe('done')
    expect((task as any).motif).toBe('focus')
  })

  it('returns true on successful API call', async () => {
    const { api } = await import('../../lib/api')
    vi.mocked(api).mockResolvedValueOnce({ ok: true, json: async () => ({}) } as any)
    const { usePlanStore } = await import('../plan')
    const store = usePlanStore()

    const result = await store.patchTaskFields('task-abc', { text: 'Updated' })
    expect(result).toBe(true)
  })

  it('returns false on API error and does not mutate plan', async () => {
    const { api } = await import('../../lib/api')
    vi.mocked(api).mockResolvedValueOnce({ ok: false, json: async () => ({}) } as any)
    const { usePlanStore } = await import('../plan')
    const store = usePlanStore()

    store.plan = {
      date: '2026-05-01',
      anchors: {
        morning: {
          tasks: [{ id: 'task-abc', text: 'Keep me', status: 'pending', position: 0 } as any],
          notes: '',
        },
      },
    } as any

    const result = await store.patchTaskFields('task-abc', { status: 'done' })
    expect(result).toBe(false)
    expect(store.plan!.anchors.morning.tasks[0].status).toBe('pending')
  })
})

describe('usePlanStore – moveTask optimistic updates', () => {
  beforeEach(() => {
    setActivePinia(createPinia())
    vi.clearAllMocks()
  })

  it('removes task from in-memory plan even when toDate is not cached', async () => {
    const { usePlanStore } = await import('../plan')
    const store = usePlanStore()

    // Pin activeDate so the fromDate lookup matches regardless of real calendar date
    store.activeDate = '2026-05-01'

    // Set active plan (fromDate) — toDate '2026-05-05' is NOT in plans cache
    store.plan = {
      date: '2026-05-01',
      anchors: {
        morning: {
          tasks: [{ id: 'task-xyz', text: 'Move me', status: 'pending', position: 0 } as any],
          notes: '',
        },
      },
    } as any
    // Ensure toDate is absent from range cache
    delete (store.plans as any)['2026-05-05']

    await store.moveTask('task-xyz', '2026-05-01', 'morning', '2026-05-05', 'morning')

    // Task must be removed from the active day's anchor even though toDate wasn't cached
    expect(store.plan!.anchors.morning.tasks).toHaveLength(0)
  })

  it('inserts task into toDate when it is in plans cache, even if fromDay is not active', async () => {
    const { usePlanStore } = await import('../plan')
    const store = usePlanStore()

    // fromDate is in range cache (not the active plan)
    const fromTask = { id: 'task-xyz', text: 'Move me', status: 'pending', position: 0 } as any
    store.plans['2026-04-30'] = {
      date: '2026-04-30',
      anchors: { morning: { tasks: [fromTask], notes: '' } },
    } as any
    // toDate is also in range cache
    store.plans['2026-05-01'] = {
      date: '2026-05-01',
      anchors: { morning: { tasks: [], notes: '' } },
    } as any

    await store.moveTask('task-xyz', '2026-04-30', 'morning', '2026-05-01', 'morning')

    expect(store.plans['2026-04-30'].anchors.morning.tasks).toHaveLength(0)
    expect(store.plans['2026-05-01'].anchors.morning.tasks).toHaveLength(1)
    expect(store.plans['2026-05-01'].anchors.morning.tasks[0].id).toBe('task-xyz')
  })
})

describe('usePlanStore – moveTaskToAnchor', () => {
  beforeEach(() => {
    setActivePinia(createPinia())
    vi.clearAllMocks()
  })

  it('PATCHes /api/tasks/:id with plan_date and anchor_id', async () => {
    const { api } = await import('../../lib/api')
    vi.mocked(api).mockResolvedValueOnce({ ok: true, json: async () => ({}) } as any)
    const { usePlanStore } = await import('../plan')
    const store = usePlanStore()

    await store.moveTaskToAnchor({ taskId: 'task-1', newDate: '2026-05-05', anchorId: 'anchor-a' })

    expect(vi.mocked(api)).toHaveBeenCalledWith(
      '/api/tasks/task-1',
      expect.objectContaining({
        method: 'PATCH',
        body: JSON.stringify({ plan_date: '2026-05-05', anchor_id: 'anchor-a' }),
      }),
    )
  })

  it('optimistically removes task from source and inserts into target when both are cached', async () => {
    const { api } = await import('../../lib/api')
    vi.mocked(api).mockResolvedValueOnce({ ok: true, json: async () => ({}) } as any)
    const { usePlanStore } = await import('../plan')
    const store = usePlanStore()

    const task = { id: 'task-1', text: 'Drag me', status: 'pending', position: 0 } as any
    store.plans['2026-05-01'] = {
      date: '2026-05-01',
      anchors: { morning: { tasks: [task], notes: '' } },
    } as any
    store.plans['2026-05-03'] = {
      date: '2026-05-03',
      anchors: { 'deep-work': { tasks: [], notes: '' } },
    } as any

    await store.moveTaskToAnchor({ taskId: 'task-1', newDate: '2026-05-03', anchorId: 'deep-work' })

    expect(store.plans['2026-05-01'].anchors.morning.tasks).toHaveLength(0)
    expect(store.plans['2026-05-03'].anchors['deep-work'].tasks).toHaveLength(1)
    expect(store.plans['2026-05-03'].anchors['deep-work'].tasks[0].id).toBe('task-1')
  })

  it('optimistically removes from source only when target day is not cached', async () => {
    const { api } = await import('../../lib/api')
    vi.mocked(api).mockResolvedValueOnce({ ok: true, json: async () => ({}) } as any)
    const { usePlanStore } = await import('../plan')
    const store = usePlanStore()

    const task = { id: 'task-2', text: 'Move me', status: 'pending', position: 0 } as any
    store.plans['2026-05-01'] = {
      date: '2026-05-01',
      anchors: { morning: { tasks: [task], notes: '' } },
    } as any
    // Target day intentionally absent from cache
    delete (store.plans as any)['2026-05-07']

    await store.moveTaskToAnchor({ taskId: 'task-2', newDate: '2026-05-07', anchorId: 'evening' })

    expect(store.plans['2026-05-01'].anchors.morning.tasks).toHaveLength(0)
    expect(store.plans['2026-05-07']).toBeUndefined()
  })

  it('also removes from active plan when task lives in plan (not plans cache)', async () => {
    const { api } = await import('../../lib/api')
    vi.mocked(api).mockResolvedValueOnce({ ok: true, json: async () => ({}) } as any)
    const { usePlanStore } = await import('../plan')
    const store = usePlanStore()

    const task = { id: 'task-3', text: 'Active day task', status: 'pending', position: 0 } as any
    store.plan = {
      date: '2026-05-02',
      anchors: { morning: { tasks: [task], notes: '' } },
      acknowledgements: {},
      check_in_log: [],
    } as any

    await store.moveTaskToAnchor({ taskId: 'task-3', newDate: '2026-05-05', anchorId: 'afternoon' })

    expect(store.plan!.anchors.morning.tasks).toHaveLength(0)
  })
})
