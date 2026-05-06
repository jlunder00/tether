import { describe, it, expect, vi, beforeEach } from 'vitest'
import { setActivePinia, createPinia } from 'pinia'

vi.mock('../../lib/api', () => ({
  api: vi.fn(() => Promise.resolve({ ok: false, json: async () => ({}) })),
}))

describe('useICalStore', () => {
  beforeEach(() => {
    setActivePinia(createPinia())
    vi.clearAllMocks()
  })

  // ── initial state ──────────────────────────────────────────────────────────

  describe('initial state', () => {
    it('starts with importing=false, lastResult=null, lastError=null', async () => {
      const { useICalStore } = await import('../ical')
      const store = useICalStore()
      expect(store.importing).toBe(false)
      expect(store.lastResult).toBeNull()
      expect(store.lastError).toBeNull()
    })
  })

  // ── importFile ─────────────────────────────────────────────────────────────

  describe('importFile', () => {
    it('sends a multipart POST to /api/ical/import', async () => {
      const { api } = await import('../../lib/api')
      const mockApi = vi.mocked(api).mockResolvedValueOnce({
        ok: true,
        status: 200,
        json: async () => ({ imported: 3, updated: 1, skipped: 0, errors: [], total_events: 4 }),
      } as any)

      const { useICalStore } = await import('../ical')
      const store = useICalStore()
      const file = new File(['BEGIN:VCALENDAR\nEND:VCALENDAR'], 'test.ics', { type: 'text/calendar' })
      await store.importFile(file, false)

      expect(mockApi).toHaveBeenCalledOnce()
      const [url, init] = mockApi.mock.calls[0]
      expect(url).toBe('/api/ical/import')
      expect((init as RequestInit).method).toBe('POST')
      expect((init as RequestInit).body).toBeInstanceOf(FormData)
    })

    it('appends skip_all_day=true to query string when requested', async () => {
      const { api } = await import('../../lib/api')
      const mockApi = vi.mocked(api).mockResolvedValueOnce({
        ok: true,
        status: 200,
        json: async () => ({ imported: 0, updated: 0, skipped: 0, errors: [], total_events: 0 }),
      } as any)

      const { useICalStore } = await import('../ical')
      const store = useICalStore()
      const file = new File(['BEGIN:VCALENDAR'], 'test.ics', { type: 'text/calendar' })
      await store.importFile(file, true)

      const [url] = mockApi.mock.calls[0]
      expect(String(url)).toContain('skip_all_day=true')
    })

    it('sets lastResult on success', async () => {
      const { api } = await import('../../lib/api')
      vi.mocked(api).mockResolvedValueOnce({
        ok: true,
        status: 200,
        json: async () => ({ imported: 3, updated: 1, skipped: 0, errors: [], total_events: 4 }),
      } as any)

      const { useICalStore } = await import('../ical')
      const store = useICalStore()
      const file = new File(['BEGIN:VCALENDAR'], 'test.ics', { type: 'text/calendar' })
      const result = await store.importFile(file, false)

      expect(result?.imported).toBe(3)
      expect(result?.updated).toBe(1)
      expect(store.lastResult?.imported).toBe(3)
      expect(store.lastError).toBeNull()
    })

    it('sets lastError for 413 (file too large)', async () => {
      const { api } = await import('../../lib/api')
      vi.mocked(api).mockResolvedValueOnce({
        ok: false,
        status: 413,
        json: async () => ({ detail: 'File too large' }),
      } as any)

      const { useICalStore } = await import('../ical')
      const store = useICalStore()
      const file = new File(['x'], 'big.ics', { type: 'text/calendar' })
      const result = await store.importFile(file, false)

      expect(result).toBeNull()
      expect(store.lastError).toContain('too large')
    })

    it('sets lastError for 422 (invalid ICS)', async () => {
      const { api } = await import('../../lib/api')
      vi.mocked(api).mockResolvedValueOnce({
        ok: false,
        status: 422,
        json: async () => ({ detail: 'Not a valid ICS file' }),
      } as any)

      const { useICalStore } = await import('../ical')
      const store = useICalStore()
      const file = new File(['not ics'], 'bad.ics', { type: 'text/calendar' })
      const result = await store.importFile(file, false)

      expect(result).toBeNull()
      expect(store.lastError).toMatch(/invalid|not a valid/i)
    })

    it('sets lastError for 502 (remote fetch failed)', async () => {
      const { api } = await import('../../lib/api')
      vi.mocked(api).mockResolvedValueOnce({
        ok: false,
        status: 502,
        json: async () => ({ detail: 'Failed to fetch remote URL' }),
      } as any)

      const { useICalStore } = await import('../ical')
      const store = useICalStore()
      const file = new File(['x'], 'x.ics', { type: 'text/calendar' })
      const result = await store.importFile(file, false)

      expect(result).toBeNull()
      expect(store.lastError).toMatch(/fetch|server/i)
    })

    it('sets lastError on network error', async () => {
      const { api } = await import('../../lib/api')
      vi.mocked(api).mockRejectedValueOnce(new Error('Network error'))

      const { useICalStore } = await import('../ical')
      const store = useICalStore()
      const file = new File(['x'], 'x.ics', { type: 'text/calendar' })
      const result = await store.importFile(file, false)

      expect(result).toBeNull()
      expect(store.lastError).toBeTruthy()
    })

    it('clears lastError when starting a new import', async () => {
      const { api } = await import('../../lib/api')
      vi.mocked(api).mockResolvedValueOnce({
        ok: true,
        status: 200,
        json: async () => ({ imported: 0, updated: 0, skipped: 0, errors: [], total_events: 0 }),
      } as any)

      const { useICalStore } = await import('../ical')
      const store = useICalStore()
      store.lastError = 'old error'
      const file = new File(['x'], 'x.ics', { type: 'text/calendar' })
      await store.importFile(file, false)

      expect(store.lastError).toBeNull()
    })

    it('sets importing=false after completion', async () => {
      const { api } = await import('../../lib/api')
      vi.mocked(api).mockResolvedValueOnce({
        ok: true,
        status: 200,
        json: async () => ({ imported: 0, updated: 0, skipped: 0, errors: [], total_events: 0 }),
      } as any)

      const { useICalStore } = await import('../ical')
      const store = useICalStore()
      const file = new File(['x'], 'x.ics', { type: 'text/calendar' })
      await store.importFile(file, false)

      expect(store.importing).toBe(false)
    })
  })

  // ── importUrl ──────────────────────────────────────────────────────────────

  describe('importUrl', () => {
    it('sends a JSON POST to /api/ical/import with the url', async () => {
      const { api } = await import('../../lib/api')
      const mockApi = vi.mocked(api).mockResolvedValueOnce({
        ok: true,
        status: 200,
        json: async () => ({ imported: 2, updated: 0, skipped: 0, errors: [], total_events: 2 }),
      } as any)

      const { useICalStore } = await import('../ical')
      const store = useICalStore()
      await store.importUrl('webcal://example.com/feed.ics', false)

      expect(mockApi).toHaveBeenCalledOnce()
      const [url, init] = mockApi.mock.calls[0]
      expect(String(url)).toBe('/api/ical/import')
      expect((init as RequestInit).method).toBe('POST')
      const body = JSON.parse((init as RequestInit).body as string)
      expect(body.url).toBe('webcal://example.com/feed.ics')
    })

    it('appends skip_all_day=true to query string when requested', async () => {
      const { api } = await import('../../lib/api')
      const mockApi = vi.mocked(api).mockResolvedValueOnce({
        ok: true,
        status: 200,
        json: async () => ({ imported: 0, updated: 0, skipped: 0, errors: [], total_events: 0 }),
      } as any)

      const { useICalStore } = await import('../ical')
      const store = useICalStore()
      await store.importUrl('https://example.com/feed.ics', true)

      const [url] = mockApi.mock.calls[0]
      expect(String(url)).toContain('skip_all_day=true')
    })

    it('sets lastResult on success', async () => {
      const { api } = await import('../../lib/api')
      vi.mocked(api).mockResolvedValueOnce({
        ok: true,
        status: 200,
        json: async () => ({ imported: 2, updated: 0, skipped: 1, errors: [], total_events: 3 }),
      } as any)

      const { useICalStore } = await import('../ical')
      const store = useICalStore()
      const result = await store.importUrl('https://example.com/feed.ics', false)

      expect(result?.imported).toBe(2)
      expect(result?.skipped).toBe(1)
      expect(store.lastResult?.imported).toBe(2)
      expect(store.lastError).toBeNull()
    })

    it('sets lastError for 422 (private address blocked)', async () => {
      const { api } = await import('../../lib/api')
      vi.mocked(api).mockResolvedValueOnce({
        ok: false,
        status: 422,
        json: async () => ({ detail: 'URL targets a private address' }),
      } as any)

      const { useICalStore } = await import('../ical')
      const store = useICalStore()
      const result = await store.importUrl('http://192.168.1.1/feed.ics', false)

      expect(result).toBeNull()
      expect(store.lastError).toBeTruthy()
    })

    it('sets lastError for 502 (remote fetch failed)', async () => {
      const { api } = await import('../../lib/api')
      vi.mocked(api).mockResolvedValueOnce({
        ok: false,
        status: 502,
        json: async () => ({ detail: 'Upstream timeout' }),
      } as any)

      const { useICalStore } = await import('../ical')
      const store = useICalStore()
      const result = await store.importUrl('https://example.com/feed.ics', false)

      expect(result).toBeNull()
      expect(store.lastError).toMatch(/fetch|server|remote/i)
    })

    it('sets importing=false after completion', async () => {
      const { api } = await import('../../lib/api')
      vi.mocked(api).mockResolvedValueOnce({
        ok: true,
        status: 200,
        json: async () => ({ imported: 0, updated: 0, skipped: 0, errors: [], total_events: 0 }),
      } as any)

      const { useICalStore } = await import('../ical')
      const store = useICalStore()
      await store.importUrl('https://example.com/feed.ics', false)

      expect(store.importing).toBe(false)
    })
  })

  // ── clearResult ────────────────────────────────────────────────────────────

  describe('clearResult', () => {
    it('resets lastResult and lastError to null', async () => {
      const { useICalStore } = await import('../ical')
      const store = useICalStore()
      store.lastError = 'some error'
      store.lastResult = { imported: 1, updated: 0, skipped: 0, errors: [], total_events: 1 }
      store.clearResult()
      expect(store.lastResult).toBeNull()
      expect(store.lastError).toBeNull()
    })
  })
})
