// Isolated store test — no vi.mock on the suppressions store itself so we exercise real code.
import { describe, it, expect, vi, beforeEach } from 'vitest'
import { createPinia, setActivePinia } from 'pinia'

vi.mock('../../lib/api', () => ({ api: vi.fn() }))

import { api } from '../../lib/api'
import { useSuppressionsStore } from '../suppressions'

describe('useSuppressionsStore', () => {
  beforeEach(() => {
    setActivePinia(createPinia())
    vi.resetAllMocks()
  })

  it('returns empty array and no error on 404 (endpoint not yet implemented)', async () => {
    vi.mocked(api).mockResolvedValue(new Response('Not Found', { status: 404 }) as Response)
    const store = useSuppressionsStore()
    await store.fetch()
    expect(store.suppressions).toEqual([])
    expect(store.error).toBeNull()
    expect(store.loading).toBe(false)
  })

  it('returns suppressions array on 200', async () => {
    const fixture = [
      { id: 's-1', scope_key: 'topic/morning', reason: 'quiet hours', source: 'beacon_decision', created_at: '2026-05-22T00:00:00Z', expires_at: null },
    ]
    vi.mocked(api).mockResolvedValue(new Response(JSON.stringify(fixture), { status: 200, headers: { 'Content-Type': 'application/json' } }) as Response)
    const store = useSuppressionsStore()
    await store.fetch()
    expect(store.suppressions).toEqual(fixture)
    expect(store.error).toBeNull()
  })

  it('sets error string on non-200 non-404 response', async () => {
    vi.mocked(api).mockResolvedValue(new Response('Server Error', { status: 500 }) as Response)
    const store = useSuppressionsStore()
    await store.fetch()
    expect(store.suppressions).toEqual([])
    expect(store.error).toContain('500')
  })

  it('sets error on network failure', async () => {
    vi.mocked(api).mockRejectedValue(new Error('Network error'))
    const store = useSuppressionsStore()
    await store.fetch()
    expect(store.suppressions).toEqual([])
    expect(store.error).toContain('Network error')
  })
})
