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

  describe('connectGCal', () => {
    it('navigates to the Google Calendar OAuth URL', async () => {
      // happy-dom allows direct assignment to window.location.href
      const { useIntegrationsStore } = await import('../integrations')
      const store = useIntegrationsStore()
      store.connectGCal()

      expect(window.location.href).toContain('/api/integrations/google/connect')
    })
  })
})
