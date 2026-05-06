import { describe, it, expect, vi, beforeEach } from 'vitest'
import { setActivePinia, createPinia } from 'pinia'
import type { Connection } from '../../types/connections'

vi.mock('../../lib/api', () => ({
  api: vi.fn(() => Promise.resolve({ ok: false, json: async () => ({}) })),
}))

vi.mock('../auth', () => ({
  useAuthStore: vi.fn(() => ({ user: { user_id: 'user-me-uuid' } })),
}))

function makeConnection(overrides: Partial<Connection> = {}): Connection {
  return {
    id: 1,
    user_a: 'user-me-uuid',
    user_b: 'user-other-uuid',
    status: 'accepted',
    initiated_by: 'user-me-uuid',
    auto_schedule: false,
    created_at: '2024-01-01T00:00:00Z',
    updated_at: '2024-01-01T00:00:00Z',
    other_user_id: 'user-other-uuid',
    other_username: 'alice',
    ...overrides,
  }
}

describe('useConnectionsStore', () => {
  beforeEach(() => {
    setActivePinia(createPinia())
    vi.restoreAllMocks()
  })

  describe('fetchConnections', () => {
    it('populates connections from the API response', async () => {
      const { api } = await import('../../lib/api')
      const data: Connection[] = [makeConnection({ id: 1 }), makeConnection({ id: 2 })]
      vi.mocked(api).mockResolvedValueOnce({
        ok: true,
        json: async () => data,
      } as any)

      const { useConnectionsStore } = await import('../connections')
      const store = useConnectionsStore()
      await store.fetchConnections()

      expect(store.connections).toHaveLength(2)
      expect(store.connections[0].id).toBe(1)
      expect(store.loading).toBe(false)
    })

    it('sets error on API failure', async () => {
      const { api } = await import('../../lib/api')
      vi.mocked(api).mockResolvedValueOnce({ ok: false, json: async () => ({}) } as any)

      const { useConnectionsStore } = await import('../connections')
      const store = useConnectionsStore()
      await store.fetchConnections()

      expect(store.error).toBeTruthy()
      expect(store.loading).toBe(false)
    })
  })

  describe('sendRequest', () => {
    it('appends the new connection to state on success', async () => {
      const { api } = await import('../../lib/api')
      const newConn = makeConnection({ id: 99, status: 'pending' })
      vi.mocked(api).mockResolvedValueOnce({
        ok: true,
        json: async () => newConn,
      } as any)

      const { useConnectionsStore } = await import('../connections')
      const store = useConnectionsStore()
      await store.sendRequest('alice')

      expect(store.connections).toHaveLength(1)
      expect(store.connections[0].id).toBe(99)
    })

    it('calls POST /api/connections/request with target_username', async () => {
      const { api } = await import('../../lib/api')
      const mockApi = vi.mocked(api).mockResolvedValueOnce({
        ok: true,
        json: async () => makeConnection({ id: 1, status: 'pending' }),
      } as any)

      const { useConnectionsStore } = await import('../connections')
      const store = useConnectionsStore()
      await store.sendRequest('bob')

      expect(mockApi).toHaveBeenCalledWith(
        '/api/connections/request',
        expect.objectContaining({
          method: 'POST',
          body: JSON.stringify({ target_username: 'bob' }),
        }),
      )
    })
  })

  describe('acceptConnection', () => {
    it('updates status to accepted in state', async () => {
      const { api } = await import('../../lib/api')
      vi.mocked(api).mockResolvedValueOnce({
        ok: true,
        json: async () => ({ id: 1, status: 'accepted' }),
      } as any)

      const { useConnectionsStore } = await import('../connections')
      const store = useConnectionsStore()
      store.connections = [makeConnection({ id: 1, status: 'pending' })]
      await store.acceptConnection(1)

      expect(store.connections[0].status).toBe('accepted')
    })
  })

  describe('declineConnection', () => {
    it('removes the connection from state when block is false (deleted)', async () => {
      const { api } = await import('../../lib/api')
      vi.mocked(api).mockResolvedValueOnce({
        ok: true,
        json: async () => ({ id: 1, deleted: true }),
      } as any)

      const { useConnectionsStore } = await import('../connections')
      const store = useConnectionsStore()
      store.connections = [makeConnection({ id: 1, status: 'pending' })]
      await store.declineConnection(1, false)

      expect(store.connections).toHaveLength(0)
    })

    it('updates status to blocked when block is true', async () => {
      const { api } = await import('../../lib/api')
      vi.mocked(api).mockResolvedValueOnce({
        ok: true,
        json: async () => ({ id: 1, status: 'blocked' }),
      } as any)

      const { useConnectionsStore } = await import('../connections')
      const store = useConnectionsStore()
      store.connections = [makeConnection({ id: 1, status: 'pending' })]
      await store.declineConnection(1, true)

      expect(store.connections[0].status).toBe('blocked')
    })
  })

  describe('toggleAutoSchedule', () => {
    it('updates auto_schedule in state', async () => {
      const { api } = await import('../../lib/api')
      const updated = makeConnection({ id: 1, auto_schedule: true })
      vi.mocked(api).mockResolvedValueOnce({
        ok: true,
        json: async () => updated,
      } as any)

      const { useConnectionsStore } = await import('../connections')
      const store = useConnectionsStore()
      store.connections = [makeConnection({ id: 1, auto_schedule: false })]
      await store.toggleAutoSchedule(1, true)

      expect(store.connections[0].auto_schedule).toBe(true)
    })

    it('calls PATCH /api/connections/{id} with auto_schedule value', async () => {
      const { api } = await import('../../lib/api')
      const mockApi = vi.mocked(api).mockResolvedValueOnce({
        ok: true,
        json: async () => makeConnection({ id: 1, auto_schedule: true }),
      } as any)

      const { useConnectionsStore } = await import('../connections')
      const store = useConnectionsStore()
      store.connections = [makeConnection({ id: 1, auto_schedule: false })]
      await store.toggleAutoSchedule(1, true)

      expect(mockApi).toHaveBeenCalledWith(
        '/api/connections/1',
        expect.objectContaining({
          method: 'PATCH',
          body: JSON.stringify({ auto_schedule: true }),
        }),
      )
    })
  })

  describe('computed: pending_incoming, pending_outgoing, accepted', () => {
    it('pending_incoming returns status=pending where initiated_by !== me', async () => {
      const { useConnectionsStore } = await import('../connections')
      const store = useConnectionsStore()
      store.connections = [
        makeConnection({ id: 1, status: 'pending', initiated_by: 'user-other-uuid' }),
        makeConnection({ id: 2, status: 'pending', initiated_by: 'user-me-uuid' }),
        makeConnection({ id: 3, status: 'accepted' }),
      ]
      expect(store.pending_incoming).toHaveLength(1)
      expect(store.pending_incoming[0].id).toBe(1)
    })

    it('pending_outgoing returns status=pending where initiated_by === me', async () => {
      const { useConnectionsStore } = await import('../connections')
      const store = useConnectionsStore()
      store.connections = [
        makeConnection({ id: 1, status: 'pending', initiated_by: 'user-me-uuid' }),
        makeConnection({ id: 2, status: 'pending', initiated_by: 'user-other-uuid' }),
      ]
      expect(store.pending_outgoing).toHaveLength(1)
      expect(store.pending_outgoing[0].id).toBe(1)
    })

    it('accepted returns only status=accepted connections', async () => {
      const { useConnectionsStore } = await import('../connections')
      const store = useConnectionsStore()
      store.connections = [
        makeConnection({ id: 1, status: 'accepted' }),
        makeConnection({ id: 2, status: 'pending', initiated_by: 'user-other-uuid' }),
        makeConnection({ id: 3, status: 'blocked' }),
      ]
      expect(store.accepted).toHaveLength(1)
      expect(store.accepted[0].id).toBe(1)
    })

    it('pending_incoming returns [] when user_id is undefined', async () => {
      const { useAuthStore } = await import('../auth')
      vi.mocked(useAuthStore).mockReturnValueOnce({ user: null } as any)

      const { useConnectionsStore } = await import('../connections')
      const store = useConnectionsStore()
      store.connections = [
        makeConnection({ id: 1, status: 'pending', initiated_by: 'user-other-uuid' }),
      ]
      expect(store.pending_incoming).toHaveLength(0)
    })

    it('pending_outgoing returns [] when user_id is undefined', async () => {
      const { useAuthStore } = await import('../auth')
      vi.mocked(useAuthStore).mockReturnValueOnce({ user: null } as any)

      const { useConnectionsStore } = await import('../connections')
      const store = useConnectionsStore()
      store.connections = [
        makeConnection({ id: 1, status: 'pending', initiated_by: 'user-me-uuid' }),
      ]
      expect(store.pending_outgoing).toHaveLength(0)
    })
  })
})
