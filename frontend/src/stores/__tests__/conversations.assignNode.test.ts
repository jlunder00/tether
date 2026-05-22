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
    // First call: PATCH, second call: refresh GET
    mockApi
      .mockResolvedValueOnce(mockResponse({ id: 'conv-1' }, true, 200))
      .mockResolvedValueOnce(mockResponse([], true, 200))

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
    mockApi
      .mockResolvedValueOnce(mockResponse({ id: 'conv-1' }, true, 200))
      .mockResolvedValueOnce(mockResponse([], true, 200))

    const store = useConversationsStore()
    await store.assignNode('conv-1', null)

    const patchCall = mockApi.mock.calls[0]
    const init = patchCall[1] as RequestInit
    const body = JSON.parse(init.body as string)
    expect(body).toEqual({ context_node_id: null })
  })

  it('calls refresh() after successful PATCH', async () => {
    mockApi
      .mockResolvedValueOnce(mockResponse({ id: 'conv-1' }, true, 200))
      .mockResolvedValueOnce(mockResponse([{ id: 'conv-1', name: 'Test' }], true, 200))

    const store = useConversationsStore()
    await store.assignNode('conv-1', 'node-abc')

    // refresh() makes a GET call — should be the second api call
    expect(mockApi).toHaveBeenCalledTimes(2)
    const refreshCall = mockApi.mock.calls[1]
    expect((refreshCall[0] as string)).toContain('/api/conversations')
    expect(refreshCall[1]).toBeUndefined() // GET has no init options
  })

  it('throws when API returns non-ok response', async () => {
    mockApi.mockResolvedValueOnce(mockResponse(null, false, 400))

    const store = useConversationsStore()
    await expect(store.assignNode('conv-1', 'node-abc')).rejects.toThrow()
  })
})
