import { describe, it, expect, vi, beforeEach } from 'vitest'
import { setActivePinia, createPinia } from 'pinia'

vi.mock('../../lib/api', () => ({
  api: vi.fn(() => Promise.resolve({ ok: false, json: async () => ({}) })),
}))

describe('useApiKeysStore', () => {
  beforeEach(() => {
    setActivePinia(createPinia())
    vi.restoreAllMocks()
  })

  describe('fetchKeys', () => {
    it('sets keys on 200', async () => {
      const { api } = await import('../../lib/api')
      vi.mocked(api).mockResolvedValueOnce({
        ok: true,
        status: 200,
        json: async () => ([
          {
            id: 'key1',
            name: 'My Key',
            key_prefix: 'ttr_abcd',
            created_at: '2026-01-01T00:00:00Z',
            last_used_at: null,
            revoked_at: null,
          },
        ]),
      } as any)

      const { useApiKeysStore } = await import('../apiKeys')
      const store = useApiKeysStore()
      await store.fetchKeys()

      expect(store.keys).toHaveLength(1)
      expect(store.keys[0].id).toBe('key1')
    })

    it('sets error on failure', async () => {
      const { api } = await import('../../lib/api')
      vi.mocked(api).mockResolvedValueOnce({
        ok: false,
        status: 500,
        json: async () => ({ detail: 'Server error' }),
      } as any)

      const { useApiKeysStore } = await import('../apiKeys')
      const store = useApiKeysStore()
      await store.fetchKeys()

      expect(store.error).toBeTruthy()
    })

    it('sets loading false after completion', async () => {
      const { api } = await import('../../lib/api')
      vi.mocked(api).mockResolvedValueOnce({
        ok: true,
        status: 200,
        json: async () => ([]),
      } as any)

      const { useApiKeysStore } = await import('../apiKeys')
      const store = useApiKeysStore()
      await store.fetchKeys()

      expect(store.loading).toBe(false)
    })
  })

  describe('createKey', () => {
    it('sets createdKey with raw_key on success', async () => {
      const { api } = await import('../../lib/api')
      vi.mocked(api).mockResolvedValueOnce({
        ok: true,
        status: 201,
        json: async () => ({
          id: 'key2',
          name: 'New Key',
          key_prefix: 'ttr_efgh',
          created_at: '2026-01-02T00:00:00Z',
          last_used_at: null,
          revoked_at: null,
          raw_key: 'ttr_efgh_supersecret',
        }),
      } as any)

      const { useApiKeysStore } = await import('../apiKeys')
      const store = useApiKeysStore()
      await store.createKey('New Key')

      expect(store.createdKey).not.toBeNull()
      expect(store.createdKey?.raw_key).toBe('ttr_efgh_supersecret')
    })

    it('sets error on failure', async () => {
      const { api } = await import('../../lib/api')
      vi.mocked(api).mockResolvedValueOnce({
        ok: false,
        status: 400,
        json: async () => ({ detail: 'Bad request' }),
      } as any)

      const { useApiKeysStore } = await import('../apiKeys')
      const store = useApiKeysStore()
      await store.createKey('Test')

      expect(store.error).toBeTruthy()
      expect(store.createdKey).toBeNull()
    })
  })

  describe('revokeKey', () => {
    it('removes key from keys array on success', async () => {
      const { api } = await import('../../lib/api')
      vi.mocked(api).mockResolvedValueOnce({
        ok: true,
        status: 204,
        json: async () => ({}),
      } as any)

      const { useApiKeysStore } = await import('../apiKeys')
      const store = useApiKeysStore()
      store.keys = [
        {
          id: 'key1',
          name: 'My Key',
          key_prefix: 'ttr_abcd',
          created_at: '2026-01-01T00:00:00Z',
          last_used_at: null,
          revoked_at: null,
        },
        {
          id: 'key2',
          name: 'Other Key',
          key_prefix: 'ttr_efgh',
          created_at: '2026-01-02T00:00:00Z',
          last_used_at: null,
          revoked_at: null,
        },
      ]
      await store.revokeKey('key1')

      expect(store.keys).toHaveLength(1)
      expect(store.keys[0].id).toBe('key2')
    })

    it('sets error on failure', async () => {
      const { api } = await import('../../lib/api')
      vi.mocked(api).mockResolvedValueOnce({
        ok: false,
        status: 500,
        json: async () => ({ detail: 'Server error' }),
      } as any)

      const { useApiKeysStore } = await import('../apiKeys')
      const store = useApiKeysStore()
      store.keys = [
        {
          id: 'key1',
          name: 'My Key',
          key_prefix: 'ttr_abcd',
          created_at: '2026-01-01T00:00:00Z',
          last_used_at: null,
          revoked_at: null,
        },
      ]
      await store.revokeKey('key1')

      expect(store.error).toBeTruthy()
      expect(store.keys).toHaveLength(1) // not removed on failure
    })
  })

  describe('clearCreatedKey', () => {
    it('sets createdKey to null', async () => {
      const { useApiKeysStore } = await import('../apiKeys')
      const store = useApiKeysStore()
      store.createdKey = {
        id: 'key1',
        name: 'My Key',
        key_prefix: 'ttr_abcd',
        created_at: '2026-01-01T00:00:00Z',
        last_used_at: null,
        revoked_at: null,
        raw_key: 'ttr_abcd_secret',
      }
      store.clearCreatedKey()

      expect(store.createdKey).toBeNull()
    })
  })
})
