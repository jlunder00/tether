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
})
