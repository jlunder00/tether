import { describe, it, expect, vi, beforeEach } from 'vitest'
import { setActivePinia, createPinia } from 'pinia'

vi.mock('../../lib/api', () => ({
  api: vi.fn(() => Promise.resolve({ ok: false, json: async () => ({}) })),
}))

describe('useEventStore', () => {
  beforeEach(() => {
    setActivePinia(createPinia())
  })

  it('moveEvent updates start_time and end_time of the matching event', async () => {
    const { useEventStore } = await import('../events')
    const store = useEventStore()

    // Seed a known event directly
    store.events.push({
      id: 'ev-1',
      title: 'Test',
      start_time: '2024-06-10T09:00:00.000Z',
      end_time: '2024-06-10T10:00:00.000Z',
      source: 'tether',
      external_id: null,
      task_id: null,
      anchor_id: null,
      color: null,
    })

    await store.moveEvent('ev-1', '2024-06-10T14:00:00.000Z', '2024-06-10T15:00:00.000Z')

    expect(store.events[0].start_time).toBe('2024-06-10T14:00:00.000Z')
    expect(store.events[0].end_time).toBe('2024-06-10T15:00:00.000Z')
  })

  it('moveEvent is a no-op for an unknown event id', async () => {
    const { useEventStore } = await import('../events')
    const store = useEventStore()
    // Should not throw
    await expect(store.moveEvent('nonexistent', '2024-01-01T00:00:00Z', '2024-01-01T01:00:00Z')).resolves.toBeUndefined()
  })

  it('createTaskAndPromote returns null when task creation fails', async () => {
    const { api } = await import('../../lib/api')
    vi.mocked(api).mockResolvedValueOnce({ ok: false, json: async () => ({}) } as any)
    const { useEventStore } = await import('../events')
    const store = useEventStore()
    const result = await store.createTaskAndPromote('2024-06-10T09:00:00Z', '2024-06-10T10:00:00Z')
    expect(result).toBeNull()
    expect(store.events).toHaveLength(0)
  })

  it('createTaskAndPromote returns taskId and adds event when both steps succeed', async () => {
    const { api } = await import('../../lib/api')
    const mockTask = { id: 'task-123', text: 'New Event', status: 'pending' }
    const mockEvent = {
      id: 'ev-456',
      title: 'New Event',
      start_time: '2024-06-10T09:00:00Z',
      end_time: '2024-06-10T10:00:00Z',
      source: 'tether',
      external_id: null,
      task_id: 'task-123',
      anchor_id: null,
      color: null,
    }
    vi.mocked(api)
      .mockResolvedValueOnce({ ok: true, json: async () => mockTask } as any)
      .mockResolvedValueOnce({ ok: true, json: async () => mockEvent } as any)
    const { useEventStore } = await import('../events')
    const store = useEventStore()
    const result = await store.createTaskAndPromote('2024-06-10T09:00:00Z', '2024-06-10T10:00:00Z')
    expect(result).toBe('task-123')
    expect(store.events).toHaveLength(1)
    expect(store.events[0].task_id).toBe('task-123')
    expect(store.events[0].id).toBe('ev-456')
  })

  it('createTaskAndPromote still returns taskId if event promotion fails', async () => {
    const { api } = await import('../../lib/api')
    const mockTask = { id: 'task-789', text: 'New Event', status: 'pending' }
    vi.mocked(api)
      .mockResolvedValueOnce({ ok: true, json: async () => mockTask } as any)
      .mockResolvedValueOnce({ ok: false, json: async () => ({}) } as any)
    const { useEventStore } = await import('../events')
    const store = useEventStore()
    const result = await store.createTaskAndPromote('2024-06-10T09:00:00Z', '2024-06-10T10:00:00Z')
    expect(result).toBe('task-789')
    // Event not added to store since promotion failed
    expect(store.events).toHaveLength(0)
  })

  // --- RRULE / recurrence tests ---

  it('fetchEvents passes through is_recurring and is_occurrence fields', async () => {
    const { api } = await import('../../lib/api')
    const mockEvents = [
      {
        id: 'ev-r1',
        title: 'Weekly standup',
        start_time: '2024-06-10T09:00:00Z',
        end_time: '2024-06-10T09:30:00Z',
        source: 'tether',
        external_id: null,
        task_id: null,
        anchor_id: null,
        color: null,
        is_recurring: true,
        is_occurrence: false,
        rrule: 'FREQ=WEEKLY;BYDAY=MO',
      },
      {
        id: 'ev-r2',
        title: 'Weekly standup',
        start_time: '2024-06-17T09:00:00Z',
        end_time: '2024-06-17T09:30:00Z',
        source: 'tether',
        external_id: null,
        task_id: null,
        anchor_id: null,
        color: null,
        is_recurring: false,
        is_occurrence: true,
        rrule: null,
      },
    ]
    vi.mocked(api).mockResolvedValueOnce({ ok: true, json: async () => mockEvents } as any)
    const { useEventStore } = await import('../events')
    const store = useEventStore()
    await store.fetchEvents('2024-06-10', '2024-06-17')
    expect(store.events).toHaveLength(2)
    expect(store.events[0].is_recurring).toBe(true)
    expect(store.events[0].rrule).toBe('FREQ=WEEKLY;BYDAY=MO')
    expect(store.events[1].is_occurrence).toBe(true)
  })

  it('setRecurrence PATCHes the event and updates rrule in local state', async () => {
    const { api } = await import('../../lib/api')
    vi.mocked(api).mockResolvedValueOnce({ ok: true, json: async () => ({}) } as any)
    const { useEventStore } = await import('../events')
    const store = useEventStore()
    store.events.push({
      id: 'ev-5',
      title: 'Recurring task',
      start_time: '2024-06-10T10:00:00Z',
      end_time: '2024-06-10T11:00:00Z',
      source: 'tether',
      external_id: null,
      task_id: 'task-5',
      anchor_id: null,
      color: null,
    })

    await store.setRecurrence('ev-5', 'FREQ=DAILY')

    expect(vi.mocked(api)).toHaveBeenCalledWith(
      '/api/events/ev-5',
      expect.objectContaining({
        method: 'PATCH',
        body: expect.stringContaining('FREQ=DAILY'),
      }),
    )
    expect(store.events[0].rrule).toBe('FREQ=DAILY')
    expect(store.events[0].is_recurring).toBe(true)
  })

  it('setRecurrence with null clears rrule and is_recurring', async () => {
    const { api } = await import('../../lib/api')
    vi.mocked(api).mockResolvedValueOnce({ ok: true, json: async () => ({}) } as any)
    const { useEventStore } = await import('../events')
    const store = useEventStore()
    store.events.push({
      id: 'ev-6',
      title: 'Was recurring',
      start_time: '2024-06-10T10:00:00Z',
      end_time: '2024-06-10T11:00:00Z',
      source: 'tether',
      external_id: null,
      task_id: null,
      anchor_id: null,
      color: null,
      is_recurring: true,
      rrule: 'FREQ=WEEKLY',
    })

    await store.setRecurrence('ev-6', null)

    expect(store.events[0].rrule).toBeNull()
    expect(store.events[0].is_recurring).toBe(false)
  })

  it('setRecurrence is a no-op for unknown event id', async () => {
    const { useEventStore } = await import('../events')
    const store = useEventStore()
    await expect(store.setRecurrence('nonexistent', 'FREQ=DAILY')).resolves.toBeUndefined()
  })
})
