import { describe, it, expect, vi, beforeEach } from 'vitest'
import { setActivePinia, createPinia } from 'pinia'

vi.mock('../../lib/api', () => ({
  api: vi.fn(() => Promise.resolve({ ok: false, json: async () => ({}) })),
}))

describe('useIntegrationsStore', () => {
  beforeEach(() => {
    setActivePinia(createPinia())
    vi.restoreAllMocks()
  })

  describe('fetchGCalStatus', () => {
    it('sets connected to true when calendars endpoint returns 200', async () => {
      const { api } = await import('../../lib/api')
      vi.mocked(api).mockResolvedValueOnce({
        ok: true,
        status: 200,
        json: async () => ({ calendars: [], selected_calendar_ids: [] }),
      } as any)

      const { useIntegrationsStore } = await import('../integrations')
      const store = useIntegrationsStore()
      await store.fetchGCalStatus()

      expect(store.gcalConnected).toBe(true)
    })

    it('sets connected to false when calendars endpoint returns 404', async () => {
      const { api } = await import('../../lib/api')
      vi.mocked(api).mockResolvedValueOnce({
        ok: false,
        status: 404,
        json: async () => ({ detail: 'Google Calendar not connected' }),
      } as any)

      const { useIntegrationsStore } = await import('../integrations')
      const store = useIntegrationsStore()
      await store.fetchGCalStatus()

      expect(store.gcalConnected).toBe(false)
    })

    it('sets connected to false when calendars endpoint returns 401', async () => {
      const { api } = await import('../../lib/api')
      vi.mocked(api).mockResolvedValueOnce({
        ok: false,
        status: 401,
        json: async () => ({ detail: 'Google token expired — reconnect' }),
      } as any)

      const { useIntegrationsStore } = await import('../integrations')
      const store = useIntegrationsStore()
      await store.fetchGCalStatus()

      expect(store.gcalConnected).toBe(false)
    })

    it('sets loading to false after fetch completes', async () => {
      const { api } = await import('../../lib/api')
      vi.mocked(api).mockResolvedValueOnce({
        ok: true,
        status: 200,
        json: async () => ({ calendars: [], selected_calendar_ids: [] }),
      } as any)

      const { useIntegrationsStore } = await import('../integrations')
      const store = useIntegrationsStore()
      await store.fetchGCalStatus()

      expect(store.loading).toBe(false)
    })

    it('sets connected to false on network error', async () => {
      const { api } = await import('../../lib/api')
      vi.mocked(api).mockRejectedValueOnce(new Error('Network error'))

      const { useIntegrationsStore } = await import('../integrations')
      const store = useIntegrationsStore()
      await store.fetchGCalStatus()

      expect(store.gcalConnected).toBe(false)
      expect(store.loading).toBe(false)
    })
  })

  describe('disconnectGCal', () => {
    it('sets connected to false after successful disconnect', async () => {
      const { api } = await import('../../lib/api')
      vi.mocked(api).mockResolvedValueOnce({
        ok: true,
        json: async () => ({ ok: true }),
      } as any)

      const { useIntegrationsStore } = await import('../integrations')
      const store = useIntegrationsStore()
      store.gcalConnected = true
      await store.disconnectGCal()

      expect(store.gcalConnected).toBe(false)
    })

    it('calls POST /api/integrations/google/disconnect', async () => {
      const { api } = await import('../../lib/api')
      const mockApi = vi.mocked(api).mockResolvedValueOnce({
        ok: true,
        json: async () => ({ ok: true }),
      } as any)

      const { useIntegrationsStore } = await import('../integrations')
      const store = useIntegrationsStore()
      await store.disconnectGCal()

      expect(mockApi).toHaveBeenCalledWith(
        '/api/integrations/google/disconnect',
        expect.objectContaining({ method: 'POST' }),
      )
    })

    it('keeps connected true if disconnect request fails', async () => {
      const { api } = await import('../../lib/api')
      vi.mocked(api).mockResolvedValueOnce({
        ok: false,
        json: async () => ({ detail: 'Error' }),
      } as any)

      const { useIntegrationsStore } = await import('../integrations')
      const store = useIntegrationsStore()
      store.gcalConnected = true
      await store.disconnectGCal()

      expect(store.gcalConnected).toBe(true)
    })
  })

  describe('syncNow', () => {
    it('sets lastSyncedAt to a valid ISO string and clears error on success', async () => {
      const { api } = await import('../../lib/api')
      vi.mocked(api).mockResolvedValueOnce({
        ok: true,
        json: async () => ({ ok: true }),
      } as any)

      const { useIntegrationsStore } = await import('../integrations')
      const store = useIntegrationsStore()
      await store.syncNow()

      expect(store.lastSyncedAt).toBeTypeOf('string')
      expect(() => new Date(store.lastSyncedAt as string).toISOString()).not.toThrow()
      expect(store.error).toBeNull()
      expect(store.loading).toBe(false)
    })

    it('calls POST /api/integrations/google/sync', async () => {
      const { api } = await import('../../lib/api')
      const mockApi = vi.mocked(api).mockResolvedValueOnce({
        ok: true,
        json: async () => ({ ok: true }),
      } as any)

      const { useIntegrationsStore } = await import('../integrations')
      const store = useIntegrationsStore()
      await store.syncNow()

      expect(mockApi).toHaveBeenCalledWith(
        '/api/integrations/google/sync',
        expect.objectContaining({ method: 'POST' }),
      )
    })

    it('sets an error message and leaves lastSyncedAt null on failure', async () => {
      const { api } = await import('../../lib/api')
      vi.mocked(api).mockResolvedValueOnce({
        ok: false,
        json: async () => ({ detail: 'oops' }),
      } as any)

      const { useIntegrationsStore } = await import('../integrations')
      const store = useIntegrationsStore()
      await store.syncNow()

      expect(store.error).toBe('Sync failed. Please try again.')
      expect(store.lastSyncedAt).toBeNull()
    })

    it('sets an error message on network error', async () => {
      const { api } = await import('../../lib/api')
      vi.mocked(api).mockRejectedValueOnce(new Error('Network error'))

      const { useIntegrationsStore } = await import('../integrations')
      const store = useIntegrationsStore()
      await store.syncNow()

      expect(store.error).toBe('Sync failed. Please try again.')
      expect(store.loading).toBe(false)
    })
  })

  describe('connectGCal', () => {
    it('navigates to the Google Calendar OAuth URL', async () => {
      // happy-dom allows direct assignment to window.location.href
      const { useIntegrationsStore } = await import('../integrations')
      const store = useIntegrationsStore()
      store.connectGCal()

      expect(window.location.href).toContain('/api/integrations/google/connect')
    })
  })

  describe('fetchAnthropicStatus', () => {
    it('sets anthropicConnected to true when GET returns { connected: true }', async () => {
      const { api } = await import('../../lib/api')
      vi.mocked(api).mockResolvedValueOnce({
        ok: true,
        status: 200,
        json: async () => ({ connected: true }),
      } as any)

      const { useIntegrationsStore } = await import('../integrations')
      const store = useIntegrationsStore()
      await store.fetchAnthropicStatus()

      expect(store.anthropicConnected).toBe(true)
    })

    it('sets anthropicConnected to false when GET returns non-200', async () => {
      const { api } = await import('../../lib/api')
      vi.mocked(api).mockResolvedValueOnce({
        ok: false,
        status: 404,
        json: async () => ({}),
      } as any)

      const { useIntegrationsStore } = await import('../integrations')
      const store = useIntegrationsStore()
      await store.fetchAnthropicStatus()

      expect(store.anthropicConnected).toBe(false)
    })

    it('sets anthropicLoading to false after fetch completes', async () => {
      const { api } = await import('../../lib/api')
      vi.mocked(api).mockResolvedValueOnce({
        ok: true,
        status: 200,
        json: async () => ({ connected: false }),
      } as any)

      const { useIntegrationsStore } = await import('../integrations')
      const store = useIntegrationsStore()
      await store.fetchAnthropicStatus()

      expect(store.anthropicLoading).toBe(false)
    })
  })

  describe('startAnthropicConnect', () => {
    it('calls POST /api/integrations/anthropic/start', async () => {
      const { api } = await import('../../lib/api')
      const mockApi = vi.mocked(api).mockResolvedValueOnce({
        ok: true,
        status: 200,
        json: async () => ({ url: 'https://auth.example.com/oauth', expires_in: 300 }),
      } as any)

      const { useIntegrationsStore } = await import('../integrations')
      const store = useIntegrationsStore()
      await store.startAnthropicConnect()

      expect(mockApi).toHaveBeenCalledWith(
        '/api/integrations/anthropic/start',
        expect.objectContaining({ method: 'POST' }),
      )
    })

    it('sets anthropicAuthUrl to the returned url', async () => {
      const { api } = await import('../../lib/api')
      vi.mocked(api).mockResolvedValueOnce({
        ok: true,
        status: 200,
        json: async () => ({ url: 'https://auth.example.com/oauth', expires_in: 300 }),
      } as any)

      const { useIntegrationsStore } = await import('../integrations')
      const store = useIntegrationsStore()
      await store.startAnthropicConnect()

      expect(store.anthropicAuthUrl).toBe('https://auth.example.com/oauth')
    })

    it('sets anthropicLoading to false after completing', async () => {
      const { api } = await import('../../lib/api')
      vi.mocked(api).mockResolvedValueOnce({
        ok: true,
        status: 200,
        json: async () => ({ url: 'https://auth.example.com/oauth', expires_in: 300 }),
      } as any)

      const { useIntegrationsStore } = await import('../integrations')
      const store = useIntegrationsStore()
      await store.startAnthropicConnect()

      expect(store.anthropicLoading).toBe(false)
    })

    it('sets anthropicError on network failure', async () => {
      const { api } = await import('../../lib/api')
      vi.mocked(api).mockRejectedValueOnce(new Error('Network error'))

      const { useIntegrationsStore } = await import('../integrations')
      const store = useIntegrationsStore()
      await store.startAnthropicConnect()

      expect(store.anthropicError).toBeTruthy()
      expect(store.anthropicLoading).toBe(false)
    })
  })

  describe('completeAnthropicConnect', () => {
    it('calls POST /api/integrations/anthropic/complete with the code', async () => {
      const { api } = await import('../../lib/api')
      const mockApi = vi.mocked(api).mockResolvedValueOnce({
        ok: true,
        status: 200,
        json: async () => ({ ok: true }),
      } as any)

      const { useIntegrationsStore } = await import('../integrations')
      const store = useIntegrationsStore()
      await store.completeAnthropicConnect('abc123')

      expect(mockApi).toHaveBeenCalledWith(
        '/api/integrations/anthropic/complete',
        expect.objectContaining({
          method: 'POST',
          body: JSON.stringify({ code: 'abc123' }),
        }),
      )
    })

    it('sets anthropicConnected to true on { ok: true }', async () => {
      const { api } = await import('../../lib/api')
      vi.mocked(api).mockResolvedValueOnce({
        ok: true,
        status: 200,
        json: async () => ({ ok: true }),
      } as any)

      const { useIntegrationsStore } = await import('../integrations')
      const store = useIntegrationsStore()
      await store.completeAnthropicConnect('mycode')

      expect(store.anthropicConnected).toBe(true)
    })

    it('sets anthropicError on { ok: false, error: "..." }', async () => {
      const { api } = await import('../../lib/api')
      vi.mocked(api).mockResolvedValueOnce({
        ok: true,
        status: 200,
        json: async () => ({ ok: false, error: 'Invalid code' }),
      } as any)

      const { useIntegrationsStore } = await import('../integrations')
      const store = useIntegrationsStore()
      await store.completeAnthropicConnect('badcode')

      expect(store.anthropicError).toBe('Invalid code')
      expect(store.anthropicConnected).toBe(false)
    })

    it('handles non-JSON 5xx response gracefully', async () => {
      const { api } = await import('../../lib/api')
      vi.mocked(api).mockResolvedValueOnce({
        ok: false,
        status: 502,
        json: async () => { throw new Error('not json') },
      } as any)

      const { useIntegrationsStore } = await import('../integrations')
      const store = useIntegrationsStore()
      await store.completeAnthropicConnect('mycode')

      expect(store.anthropicError).toBe('Connection failed.')
      expect(store.anthropicLoading).toBe(false)
      expect(store.anthropicConnected).toBe(false)
    })

    it('clears anthropicAuthUrl on success', async () => {
      const { api } = await import('../../lib/api')
      vi.mocked(api).mockResolvedValueOnce({
        ok: true,
        status: 200,
        json: async () => ({ ok: true }),
      } as any)

      const { useIntegrationsStore } = await import('../integrations')
      const store = useIntegrationsStore()
      store.anthropicAuthUrl = 'https://auth.example.com/oauth'
      await store.completeAnthropicConnect('mycode')

      expect(store.anthropicAuthUrl).toBeNull()
    })
  })

  describe('clearAnthropicFlowState', () => {
    it('clears both anthropicError and anthropicAuthUrl to null', async () => {
      const { useIntegrationsStore } = await import('../integrations')
      const store = useIntegrationsStore()
      store.anthropicError = 'Some previous error'
      store.anthropicAuthUrl = 'https://auth.example.com/oauth'
      store.clearAnthropicFlowState()
      expect(store.anthropicError).toBeNull()
      expect(store.anthropicAuthUrl).toBeNull()
    })
  })

  describe('disconnectAnthropic', () => {
    it('calls DELETE /api/integrations/anthropic', async () => {
      const { api } = await import('../../lib/api')
      const mockApi = vi.mocked(api).mockResolvedValueOnce({
        ok: true,
        status: 204,
        json: async () => ({}),
      } as any)

      const { useIntegrationsStore } = await import('../integrations')
      const store = useIntegrationsStore()
      await store.disconnectAnthropic()

      expect(mockApi).toHaveBeenCalledWith(
        '/api/integrations/anthropic',
        expect.objectContaining({ method: 'DELETE' }),
      )
    })

    it('sets anthropicConnected to false on 204', async () => {
      const { api } = await import('../../lib/api')
      vi.mocked(api).mockResolvedValueOnce({
        ok: true,
        status: 204,
        json: async () => ({}),
      } as any)

      const { useIntegrationsStore } = await import('../integrations')
      const store = useIntegrationsStore()
      store.anthropicConnected = true
      await store.disconnectAnthropic()

      expect(store.anthropicConnected).toBe(false)
    })

    it('keeps anthropicConnected true and sets anthropicError on failure', async () => {
      const { api } = await import('../../lib/api')
      vi.mocked(api).mockResolvedValueOnce({
        ok: false,
        status: 500,
        json: async () => ({ detail: 'Server error' }),
      } as any)

      const { useIntegrationsStore } = await import('../integrations')
      const store = useIntegrationsStore()
      store.anthropicConnected = true
      await store.disconnectAnthropic()

      expect(store.anthropicConnected).toBe(true)
      expect(store.anthropicError).toBeTruthy()
    })
  })
})
