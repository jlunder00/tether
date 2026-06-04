/**
 * Tests for index-based loading + optimistic create in useConversationsStore.
 *
 * Stream E: conversation_index endpoint for fast tree population.
 * Shapes as proposed by conversation-index-builder teammate.
 */
import { describe, it, expect, vi, beforeEach } from 'vitest'
import { setActivePinia, createPinia } from 'pinia'
import { useConversationsStore } from '../conversations'

vi.mock('../../lib/api', () => ({ api: vi.fn() }))

import { api } from '../../lib/api'
const mockApi = vi.mocked(api)

/** Shape returned by GET /api/conversations/index (now includes state + priority) */
function makeIndexItem(overrides = {}) {
  return {
    id: 'conv-1',
    title: 'Test Conversation',
    parent_context_node_id: null as string | null,
    state: 'open' as const,
    priority: 'normal' as const,
    updated_at: '2026-01-01T00:01:00Z',
    message_count: 3,
    ...overrides,
  }
}

function mockResponse(data: unknown, ok = true, status = 200) {
  return { ok, status, json: async () => data } as Response
}

describe('useConversationsStore — index-based loading', () => {
  beforeEach(() => {
    setActivePinia(createPinia())
    mockApi.mockReset()
  })

  describe('refreshIndex()', () => {
    it('calls GET /api/conversations/index', async () => {
      mockApi.mockResolvedValue(mockResponse([]))
      const store = useConversationsStore()
      await store.refreshIndex()
      expect(mockApi).toHaveBeenCalledWith('/api/conversations/index')
    })

    it('sets indexLoaded = true after successful fetch', async () => {
      mockApi.mockResolvedValue(mockResponse([makeIndexItem()]))
      const store = useConversationsStore()
      expect(store.indexLoaded).toBe(false)
      await store.refreshIndex()
      expect(store.indexLoaded).toBe(true)
    })

    it('populates list from index items', async () => {
      const items = [
        makeIndexItem({ id: 'conv-1', title: 'Conv One', parent_context_node_id: 'node-a' }),
        makeIndexItem({ id: 'conv-2', title: 'Conv Two', parent_context_node_id: null }),
      ]
      mockApi.mockResolvedValue(mockResponse(items))
      const store = useConversationsStore()
      await store.refreshIndex()

      expect(store.list).toHaveLength(2)
      // Maps title → name
      expect(store.list[0].name).toBe('Conv One')
      expect(store.list[1].name).toBe('Conv Two')
    })

    it('maps parent_context_node_id → context_node_id in list', async () => {
      const items = [makeIndexItem({ id: 'c1', parent_context_node_id: 'node-xyz' })]
      mockApi.mockResolvedValue(mockResponse(items))
      const store = useConversationsStore()
      await store.refreshIndex()
      expect(store.list[0].context_node_id).toBe('node-xyz')
    })

    it('maps updated_at → last_message_at in list', async () => {
      const ts = '2026-03-15T10:00:00Z'
      mockApi.mockResolvedValue(mockResponse([makeIndexItem({ updated_at: ts })]))
      const store = useConversationsStore()
      await store.refreshIndex()
      expect(store.list[0].last_message_at).toBe(ts)
    })

    it('uses state from index response (not a hardcoded default)', async () => {
      mockApi.mockResolvedValue(mockResponse([
        makeIndexItem({ state: 'pending', priority: 'urgent' }),
      ]))
      const store = useConversationsStore()
      await store.refreshIndex()
      expect(store.list[0].state).toBe('pending')
      expect(store.list[0].priority).toBe('urgent')
    })

    it('updates state and priority on existing items from index (index is accurate)', async () => {
      const store = useConversationsStore()
      // Simulate an item already in list (e.g. from a prior refresh with stale data)
      store.list.push({
        id: 'conv-1', name: 'Old Name', type: 'interactive', priority: 'normal',
        state: 'open', context_node_id: null, thread_key: null,
        is_system: false, created_at: '2026-01-01T00:00:00Z',
        last_message_at: '2026-01-01T00:00:00Z', folder_name: null,
      })

      mockApi.mockResolvedValue(mockResponse([
        makeIndexItem({ id: 'conv-1', title: 'Updated Name', state: 'pending', priority: 'high' }),
      ]))
      await store.refreshIndex()

      const item = store.list.find(c => c.id === 'conv-1')
      // Index is now the authoritative source for state + priority
      expect(item?.state).toBe('pending')
      expect(item?.priority).toBe('high')
      // Fields not in the index (thread_key, is_system) are preserved
      expect(item?.thread_key).toBeNull()
    })

    it('indexLoaded stays false on fetch error', async () => {
      mockApi.mockResolvedValue(mockResponse(null, false, 500))
      const store = useConversationsStore()
      await store.refreshIndex()
      expect(store.indexLoaded).toBe(false)
    })
  })
})

describe('useConversationsStore — refreshForNode (silent background upsert)', () => {
  beforeEach(() => {
    setActivePinia(createPinia())
    mockApi.mockReset()
  })

  function makeFullConv(id: string, nodeId: string | null = null) {
    return {
      id, name: `Conv ${id}`, type: 'interactive' as const,
      priority: 'urgent' as const, state: 'pending' as const,
      context_node_id: nodeId, thread_key: null, is_system: false,
      created_at: '2026-01-01T00:00:00Z', last_message_at: '2026-01-01T00:01:00Z',
      folder_name: null,
    }
  }

  it('calls GET /api/conversations with context_node_id param when nodeId given', async () => {
    mockApi.mockResolvedValue(mockResponse([]))
    const store = useConversationsStore()
    await store.refreshForNode('node-abc')
    const url = mockApi.mock.calls[0][0] as string
    expect(url).toContain('context_node_id=node-abc')
  })

  it('calls GET /api/conversations without scope param when nodeId is null', async () => {
    mockApi.mockResolvedValue(mockResponse([]))
    const store = useConversationsStore()
    await store.refreshForNode(null)
    const url = mockApi.mock.calls[0][0] as string
    expect(url).not.toContain('context_node_id')
  })

  it('upserts full ConversationDetail into existing list (upgrades index stubs)', async () => {
    const store = useConversationsStore()
    // Simulate index-loaded stub with wrong state/priority
    store.list.push({ id: 'c1', name: 'Conv 1', type: 'interactive', priority: 'normal', state: 'open',
      context_node_id: 'node-x', thread_key: null, is_system: false,
      created_at: '2026-01-01T00:00:00Z', last_message_at: '2026-01-01T00:00:00Z', folder_name: null })

    const fullConv = makeFullConv('c1', 'node-x')
    mockApi.mockResolvedValue(mockResponse([fullConv]))
    await store.refreshForNode('node-x')

    // State and priority should be upgraded from index defaults
    expect(store.list.find(c => c.id === 'c1')?.state).toBe('pending')
    expect(store.list.find(c => c.id === 'c1')?.priority).toBe('urgent')
  })

  it('appends new conversations not previously in list', async () => {
    const store = useConversationsStore()
    const freshConv = makeFullConv('c-new', 'node-x')
    mockApi.mockResolvedValue(mockResponse([freshConv]))
    await store.refreshForNode('node-x')
    expect(store.list.some(c => c.id === 'c-new')).toBe(true)
  })

  it('does not replace conversations belonging to other nodes', async () => {
    const store = useConversationsStore()
    // Two conversations in different nodes
    store.list.push(
      { id: 'c1', name: 'In Node X', type: 'interactive', priority: 'normal', state: 'open',
        context_node_id: 'node-x', thread_key: null, is_system: false,
        created_at: '2026-01-01T00:00:00Z', last_message_at: '2026-01-01T00:00:00Z', folder_name: null },
      { id: 'c2', name: 'In Node Y', type: 'interactive', priority: 'urgent', state: 'open',
        context_node_id: 'node-y', thread_key: null, is_system: false,
        created_at: '2026-01-01T00:00:00Z', last_message_at: '2026-01-01T00:00:00Z', folder_name: null },
    )
    mockApi.mockResolvedValue(mockResponse([makeFullConv('c1', 'node-x')]))
    await store.refreshForNode('node-x')

    // c2 should be untouched
    expect(store.list.find(c => c.id === 'c2')?.priority).toBe('urgent')
    expect(store.list).toHaveLength(2)
  })

  it('does not set loading flag (silent — no spinner shown)', async () => {
    mockApi.mockResolvedValue(mockResponse([]))
    const store = useConversationsStore()
    const refreshPromise = store.refreshForNode('node-x')
    // loading should not be set (would show spinner if true)
    expect(store.loading).toBe(false)
    await refreshPromise
    expect(store.loading).toBe(false)
  })
})

describe('useConversationsStore — optimistic create', () => {
  beforeEach(() => {
    setActivePinia(createPinia())
    mockApi.mockReset()
  })

  it('adds a temporary entry to list BEFORE server response', async () => {
    let resolveResponse!: (v: Response) => void
    const serverResponse = new Promise<Response>(r => { resolveResponse = r })
    mockApi.mockReturnValue(serverResponse)

    const store = useConversationsStore()
    // Start create but don't await it
    const createPromise = store.create({ name: 'My New Chat' })

    // Should be in list immediately (optimistic)
    expect(store.list.some(c => c.name === 'My New Chat')).toBe(true)

    // Resolve with server response
    resolveResponse(mockResponse({
      id: 'real-id-123', name: 'My New Chat', type: 'interactive', priority: 'normal',
      state: 'open', context_node_id: null, thread_key: null, is_system: false,
      created_at: '2026-01-01T00:00:00Z', last_message_at: '2026-01-01T00:00:00Z',
      folder_name: null,
    }))

    await createPromise
  })

  it('replaces temp entry with real id after server response', async () => {
    const realConv = {
      id: 'real-server-id', name: 'New Chat', type: 'interactive' as const,
      priority: 'normal' as const, state: 'open' as const, context_node_id: null,
      thread_key: null, is_system: false, created_at: '2026-01-01T00:00:00Z',
      last_message_at: '2026-01-01T00:00:00Z', folder_name: null,
    }
    mockApi.mockResolvedValue(mockResponse(realConv))

    const store = useConversationsStore()
    await store.create({ name: 'New Chat' })

    // Should have real id, not temp
    const ids = store.list.map(c => c.id)
    expect(ids).toContain('real-server-id')
    expect(ids.some(id => id.startsWith('temp-'))).toBe(false)
    // Only one entry (temp replaced, not duplicated)
    expect(store.list.filter(c => c.name === 'New Chat')).toHaveLength(1)
  })

  it('removes temp entry on server error', async () => {
    mockApi.mockResolvedValue(mockResponse(null, false, 500))

    const store = useConversationsStore()
    const result = await store.create({ name: 'Doomed Chat' })

    expect(result).toBeNull()
    // Temp entry removed
    expect(store.list.some(c => c.name === 'Doomed Chat')).toBe(false)
  })

  it('temp entry has correct name and context_node_id immediately', async () => {
    let resolve!: (v: Response) => void
    mockApi.mockReturnValue(new Promise<Response>(r => { resolve = r }))

    const store = useConversationsStore()
    store.create({ name: 'Project Chat', context_node_id: 'node-abc' })

    const temp = store.list.find(c => c.name === 'Project Chat')
    expect(temp).toBeTruthy()
    expect(temp?.context_node_id).toBe('node-abc')

    resolve(mockResponse(null, false, 500)) // cleanup
  })

  it('temp entry id starts with "temp-" prefix', async () => {
    let resolve!: (v: Response) => void
    mockApi.mockReturnValue(new Promise<Response>(r => { resolve = r }))

    const store = useConversationsStore()
    store.create({ name: 'Temp Test' })

    const temp = store.list.find(c => c.name === 'Temp Test')
    expect(temp?.id).toMatch(/^temp-/)

    resolve(mockResponse(null, false, 500)) // cleanup
  })
})
