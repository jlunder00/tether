import { describe, it, expect, vi, beforeEach } from 'vitest'
import { setActivePinia, createPinia } from 'pinia'
import { useConversationsStore } from '../conversations'

vi.mock('../../lib/api', () => ({ api: vi.fn() }))

import { api } from '../../lib/api'
const mockApi = vi.mocked(api)

function mockResponse(data: unknown, ok = true, status = 200) {
  return {
    ok,
    status,
    json: async () => data,
  } as Response
}

describe('useConversationsStore.assignNode()', () => {
  beforeEach(() => {
    setActivePinia(createPinia())
    mockApi.mockReset()
  })

  it('calls PATCH /api/conversations/{id} with context_node_id', async () => {
    mockApi.mockResolvedValueOnce(mockResponse({ id: 'conv-1' }, true, 200))

    const store = useConversationsStore()
    await store.assignNode('conv-1', 'node-abc')

    const patchCall = mockApi.mock.calls[0]
    expect(patchCall[0]).toBe('/api/conversations/conv-1')
    const init = patchCall[1] as RequestInit
    expect(init.method).toBe('PATCH')
    const body = JSON.parse(init.body as string)
    expect(body).toEqual({ context_node_id: 'node-abc' })
  })

  it('calls PATCH with context_node_id: null when nodeId is null', async () => {
    mockApi.mockResolvedValueOnce(mockResponse({ id: 'conv-1' }, true, 200))

    const store = useConversationsStore()
    await store.assignNode('conv-1', null)

    const patchCall = mockApi.mock.calls[0]
    const init = patchCall[1] as RequestInit
    const body = JSON.parse(init.body as string)
    expect(body).toEqual({ context_node_id: null })
  })

  it('updates context_node_id in-place on the list after successful PATCH', async () => {
    mockApi.mockResolvedValueOnce(mockResponse({ id: 'conv-1' }, true, 200))

    const store = useConversationsStore()
    // Seed the list with a conversation
    store.list.push({
      id: 'conv-1', name: 'Test', type: 'interactive', priority: 'normal',
      state: 'open', context_node_id: null, thread_key: null, is_system: false,
      created_at: '2026-01-01T00:00:00Z', last_message_at: '2026-01-01T00:01:00Z',
      folder_name: null,
    } as any)

    await store.assignNode('conv-1', 'node-abc')

    // Only one API call (no refresh)
    expect(mockApi).toHaveBeenCalledTimes(1)
    // Local list updated in-place
    expect(store.list[0].context_node_id).toBe('node-abc')
  })

  it('throws when API returns non-ok response', async () => {
    mockApi.mockResolvedValueOnce(mockResponse(null, false, 400))

    const store = useConversationsStore()
    await expect(store.assignNode('conv-1', 'node-abc')).rejects.toThrow()
  })
})
