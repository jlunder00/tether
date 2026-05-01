/**
 * plan store — patchTaskFields action
 *
 * Verifies that patchTaskFields:
 *   1. PATCHes /api/tasks/:id with the given fields
 *   2. Applies an optimistic update to the in-memory plan
 *   3. Returns true on success, false on API error
 */
import { describe, it, expect, vi, beforeEach } from 'vitest'
import { setActivePinia, createPinia } from 'pinia'

vi.mock('../../lib/api', () => ({
  api: vi.fn(() => Promise.resolve({ ok: false, json: async () => ({}) })),
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
