import { describe, it, expect, vi, beforeEach } from 'vitest'
import { setActivePinia, createPinia } from 'pinia'
import { useConversationsStore } from '../conversations'

vi.mock('../../lib/api', () => ({ api: vi.fn() }))

import { api } from '../../lib/api'
const mockApi = vi.mocked(api)

function makeConv(overrides = {}) {
  return {
    id: 'conv-1',
    name: 'Test Conv',
    type: 'interactive' as const,
    priority: 'normal' as const,
    state: 'open' as const,
    context_node_id: null,
    thread_key: null,
    is_system: false,
    created_at: '2026-01-01T00:00:00Z',
    last_message_at: '2026-01-01T00:01:00Z',
    folder_name: null,
    ...overrides,
  }
}

function makeMsg(overrides = {}) {
  return {
    id: 'msg-1',
    role: 'user' as const,
    body: 'Hello',
    source: 'chat' as const,
    channel: 'web' as const,
    created_at: '2026-01-01T00:00:00Z',
    ...overrides,
  }
}

function mockResponse(data: unknown, ok = true, status = 200) {
  return {
    ok,
    status,
    json: async () => data,
  } as Response
}

describe('useConversationsStore', () => {
  beforeEach(() => {
    setActivePinia(createPinia())
    mockApi.mockReset()
  })

  describe('refresh()', () => {
    it('populates list from API response', async () => {
      const convs = [makeConv(), makeConv({ id: 'conv-2', name: 'Conv 2' })]
      mockApi.mockResolvedValue(mockResponse(convs))

      const store = useConversationsStore()
      await store.refresh()

      expect(store.list).toHaveLength(2)
      expect(store.list[0].id).toBe('conv-1')
      expect(store.list[1].id).toBe('conv-2')
    })

    it('passes state and context_node_id as query params', async () => {
      mockApi.mockResolvedValue(mockResponse([]))

      const store = useConversationsStore()
      await store.refresh({ state: 'open', context_node_id: 'node-abc' })

      const url = mockApi.mock.calls[0][0] as string
      expect(url).toContain('state=open')
      expect(url).toContain('context_node_id=node-abc')
    })

    it('sets loading true during fetch, false after', async () => {
      let resolveJson!: (v: unknown) => void
      const jsonPromise = new Promise(r => { resolveJson = r })
      mockApi.mockResolvedValue({
        ok: true,
        json: () => jsonPromise,
      } as Response)

      const store = useConversationsStore()
      const p = store.refresh()
      expect(store.loading).toBe(true)
      resolveJson([])
      await p
      expect(store.loading).toBe(false)
    })

    it('sets error on HTTP failure', async () => {
      mockApi.mockResolvedValue(mockResponse(null, false, 500))

      const store = useConversationsStore()
      await store.refresh()

      expect(store.error).toBeTruthy()
    })
  })

  describe('create()', () => {
    it('posts correct body and prepends to list', async () => {
      const newConv = makeConv({ id: 'conv-new', name: 'New Conv' })
      mockApi.mockResolvedValue(mockResponse(newConv, true, 201))

      const store = useConversationsStore()
      store.list = [makeConv()]
      const result = await store.create({ name: 'New Conv', priority: 'high' })

      expect(result).toEqual(newConv)
      expect(store.list[0].id).toBe('conv-new')
      expect(store.list).toHaveLength(2)

      const callArgs = mockApi.mock.calls[0]
      expect(callArgs[0]).toBe('/api/conversations')
      const init = callArgs[1] as RequestInit
      expect(init.method).toBe('POST')
      const body = JSON.parse(init.body as string)
      expect(body.name).toBe('New Conv')
      expect(body.priority).toBe('high')
    })

    it('returns null on failure', async () => {
      mockApi.mockResolvedValue(mockResponse(null, false, 400))

      const store = useConversationsStore()
      const result = await store.create({ name: 'Fail' })
      expect(result).toBeNull()
    })
  })

  describe('patch()', () => {
    it('sends PATCH and updates list in place', async () => {
      mockApi.mockResolvedValue(mockResponse({ ok: true }))

      const store = useConversationsStore()
      store.list = [makeConv({ id: 'c1', priority: 'normal' })]
      const ok = await store.patch('c1', { priority: 'high' })

      expect(ok).toBe(true)
      expect(store.list[0].priority).toBe('high')

      const callArgs = mockApi.mock.calls[0]
      expect(callArgs[0]).toBe('/api/conversations/c1')
      const init = callArgs[1] as RequestInit
      expect(init.method).toBe('PATCH')
    })

    it('returns false on failure', async () => {
      mockApi.mockResolvedValue(mockResponse(null, false, 400))

      const store = useConversationsStore()
      const ok = await store.patch('missing', { name: 'x' })
      expect(ok).toBe(false)
    })
  })

  describe('select()', () => {
    it('sets selectedId', async () => {
      mockApi.mockResolvedValue(mockResponse({ messages: [], has_more: false }))

      const store = useConversationsStore()
      store.select('conv-1')
      expect(store.selectedId).toBe('conv-1')
    })

    it('triggers loadMessages when messages not yet loaded', async () => {
      mockApi.mockResolvedValue(mockResponse({ messages: [], has_more: false }))

      const store = useConversationsStore()
      store.select('conv-1')

      // Give loadMessages time to run
      await vi.waitFor(() => mockApi.mock.calls.length > 0)
      expect(mockApi).toHaveBeenCalledWith('/api/conversations/conv-1/messages?limit=50')
    })

    it('does not call loadMessages if messages already loaded', async () => {
      const store = useConversationsStore()
      // Pre-populate messages
      store.messagesById.set('conv-1', [makeMsg()])
      store.select('conv-1')

      // api should not be called
      await new Promise(r => setTimeout(r, 10))
      expect(mockApi).not.toHaveBeenCalled()
    })
  })

  describe('loadMessages()', () => {
    it('stores reversed messages (newest-first API -> oldest-first display)', async () => {
      const msgs = [
        makeMsg({ id: 'msg-3', created_at: '2026-01-01T00:02:00Z' }),
        makeMsg({ id: 'msg-2', created_at: '2026-01-01T00:01:00Z' }),
        makeMsg({ id: 'msg-1', created_at: '2026-01-01T00:00:00Z' }),
      ]
      mockApi.mockResolvedValue(mockResponse({ messages: msgs, has_more: false }))

      const store = useConversationsStore()
      await store.loadMessages('conv-1')

      const stored = store.messagesById.get('conv-1')!
      expect(stored).toHaveLength(3)
      // Reversed: oldest first
      expect(stored[0].id).toBe('msg-1')
      expect(stored[1].id).toBe('msg-2')
      expect(stored[2].id).toBe('msg-3')
    })

    it('stores has_more flag', async () => {
      mockApi.mockResolvedValue(mockResponse({ messages: [], has_more: true }))

      const store = useConversationsStore()
      await store.loadMessages('conv-1')

      expect(store.hasMoreById.get('conv-1')).toBe(true)
    })
  })

  describe('loadMessagesOlder()', () => {
    it('prepends older messages and updates has_more', async () => {
      const olderMsgs = [
        makeMsg({ id: 'msg-old-2', created_at: '2025-12-31T23:59:00Z' }),
        makeMsg({ id: 'msg-old-1', created_at: '2025-12-31T23:58:00Z' }),
      ]
      mockApi.mockResolvedValue(mockResponse({ messages: olderMsgs, has_more: false }))

      const store = useConversationsStore()
      const currentMsgs = [makeMsg({ id: 'msg-current-1' })]
      store.messagesById.set('conv-1', currentMsgs)
      store.hasMoreById.set('conv-1', true)

      await store.loadMessagesOlder('conv-1')

      const url = mockApi.mock.calls[0][0] as string
      expect(url).toContain('before_id=msg-current-1')

      const stored = store.messagesById.get('conv-1')!
      // older prepended, reversed: oldest-first
      expect(stored[0].id).toBe('msg-old-1')
      expect(stored[1].id).toBe('msg-old-2')
      expect(stored[2].id).toBe('msg-current-1')
      expect(store.hasMoreById.get('conv-1')).toBe(false)
    })

    it('does nothing if has_more is false', async () => {
      const store = useConversationsStore()
      store.messagesById.set('conv-1', [makeMsg()])
      store.hasMoreById.set('conv-1', false)

      await store.loadMessagesOlder('conv-1')
      expect(mockApi).not.toHaveBeenCalled()
    })
  })

  describe('appendMessage()', () => {
    it('appends to existing messages', () => {
      const store = useConversationsStore()
      store.messagesById.set('conv-1', [makeMsg({ id: 'msg-1' })])

      store.appendMessage('conv-1', makeMsg({ id: 'msg-2' }))

      const msgs = store.messagesById.get('conv-1')!
      expect(msgs).toHaveLength(2)
      expect(msgs[1].id).toBe('msg-2')
    })

    it('creates new array if conversation has no messages yet', () => {
      const store = useConversationsStore()
      store.appendMessage('new-conv', makeMsg({ id: 'msg-1' }))

      const msgs = store.messagesById.get('new-conv')!
      expect(msgs).toHaveLength(1)
    })
  })
})
