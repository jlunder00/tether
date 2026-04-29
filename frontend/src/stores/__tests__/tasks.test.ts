import { describe, it, expect, vi, beforeEach } from 'vitest'
import { setActivePinia, createPinia } from 'pinia'

vi.mock('../../lib/api', () => ({
  api: vi.fn(() => Promise.resolve({ ok: false, json: async () => ({}) })),
}))

describe('useTasksStore', () => {
  beforeEach(() => {
    setActivePinia(createPinia())
    vi.clearAllMocks()
  })

  // ── setTaskRrule ──────────────────────────────────────────────────────────────

  it('setTaskRrule PATCHes /api/tasks/:id/rrule with the given rrule string', async () => {
    const { api } = await import('../../lib/api')
    vi.mocked(api).mockResolvedValueOnce({ ok: true, json: async () => ({}) } as any)
    const { useTasksStore } = await import('../tasks')
    const store = useTasksStore()

    await store.setTaskRrule('task-1', 'FREQ=WEEKLY;BYDAY=MO')

    expect(vi.mocked(api)).toHaveBeenCalledWith(
      '/api/tasks/task-1/rrule',
      expect.objectContaining({
        method: 'PATCH',
        body: expect.stringContaining('FREQ=WEEKLY;BYDAY=MO'),
      }),
    )
  })

  it('setTaskRrule with null sends null in the body to clear recurrence', async () => {
    const { api } = await import('../../lib/api')
    vi.mocked(api).mockResolvedValueOnce({ ok: true, json: async () => ({}) } as any)
    const { useTasksStore } = await import('../tasks')
    const store = useTasksStore()

    await store.setTaskRrule('task-2', null)

    expect(vi.mocked(api)).toHaveBeenCalledWith(
      '/api/tasks/task-2/rrule',
      expect.objectContaining({
        method: 'PATCH',
        body: JSON.stringify({ rrule: null }),
      }),
    )
  })

  it('setTaskRrule resolves without throwing when API returns error', async () => {
    const { api } = await import('../../lib/api')
    vi.mocked(api).mockResolvedValueOnce({ ok: false, json: async () => ({}) } as any)
    const { useTasksStore } = await import('../tasks')
    const store = useTasksStore()

    await expect(store.setTaskRrule('task-3', 'FREQ=DAILY')).resolves.toBeUndefined()
  })

  // ── deleteTask ────────────────────────────────────────────────────────────────

  it('deleteTask with no scope calls DELETE /api/tasks/:id with no query params', async () => {
    const { api } = await import('../../lib/api')
    vi.mocked(api).mockResolvedValueOnce({ ok: true, json: async () => ({}) } as any)
    const { useTasksStore } = await import('../tasks')
    const store = useTasksStore()

    await store.deleteTask('task-4')

    const call = vi.mocked(api).mock.calls[0]
    expect(call[0]).toBe('/api/tasks/task-4')
    expect((call[1] as RequestInit).method).toBe('DELETE')
  })

  it('deleteTask with scope="this" appends scope and original_date query params', async () => {
    const { api } = await import('../../lib/api')
    vi.mocked(api).mockResolvedValueOnce({ ok: true, json: async () => ({}) } as any)
    const { useTasksStore } = await import('../tasks')
    const store = useTasksStore()

    await store.deleteTask('task-5', 'this', '2024-06-10')

    const call = vi.mocked(api).mock.calls[0]
    expect(call[0]).toContain('scope=this')
    expect(call[0]).toContain('original_date=2024-06-10')
  })

  it('deleteTask with scope="this_and_future" appends scope=this_and_future', async () => {
    const { api } = await import('../../lib/api')
    vi.mocked(api).mockResolvedValueOnce({ ok: true, json: async () => ({}) } as any)
    const { useTasksStore } = await import('../tasks')
    const store = useTasksStore()

    await store.deleteTask('task-6', 'this_and_future', '2024-06-10')

    const call = vi.mocked(api).mock.calls[0]
    expect(call[0]).toContain('scope=this_and_future')
    expect(call[0]).toContain('original_date=2024-06-10')
  })

  it('deleteTask with scope="all" appends only scope=all (no original_date)', async () => {
    const { api } = await import('../../lib/api')
    vi.mocked(api).mockResolvedValueOnce({ ok: true, json: async () => ({}) } as any)
    const { useTasksStore } = await import('../tasks')
    const store = useTasksStore()

    await store.deleteTask('task-7', 'all')

    const call = vi.mocked(api).mock.calls[0]
    expect(call[0]).toContain('scope=all')
    expect(call[0]).not.toContain('original_date')
  })

  it('deleteTask resolves without throwing when API returns error', async () => {
    const { api } = await import('../../lib/api')
    vi.mocked(api).mockResolvedValueOnce({ ok: false, json: async () => ({}) } as any)
    const { useTasksStore } = await import('../tasks')
    const store = useTasksStore()

    await expect(store.deleteTask('task-8')).resolves.toBeUndefined()
  })
})
