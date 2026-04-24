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

  it('createEvent adds a local optimistic event when backend returns 4xx', async () => {
    const { useEventStore } = await import('../events')
    const store = useEventStore()
    const result = await store.createEvent('2024-06-10T09:00:00Z', '2024-06-10T10:00:00Z', 'New Event')
    expect(result).not.toBeNull()
    expect(store.events).toHaveLength(1)
    expect(store.events[0].title).toBe('New Event')
    expect(store.events[0].start_time).toBe('2024-06-10T09:00:00Z')
    expect(store.events[0].source).toBe('tether')
    expect(store.events[0].task_id).toBeNull()
  })

  it('createEvent uses server response when backend returns 2xx', async () => {
    const { api } = await import('../../lib/api')
    const mockEvent = {
      id: 'server-id',
      title: 'New Event',
      start_time: '2024-06-10T09:00:00Z',
      end_time: '2024-06-10T10:00:00Z',
      source: 'tether',
      external_id: null,
      task_id: null,
      anchor_id: null,
      color: null,
    }
    vi.mocked(api).mockResolvedValueOnce({ ok: true, json: async () => mockEvent } as any)
    const { useEventStore } = await import('../events')
    const store = useEventStore()
    const result = await store.createEvent('2024-06-10T09:00:00Z', '2024-06-10T10:00:00Z', 'New Event')
    expect(result?.id).toBe('server-id')
    expect(store.events[0].id).toBe('server-id')
  })
})
