import { describe, it, expect, vi, beforeEach } from 'vitest'
import { setActivePinia, createPinia } from 'pinia'
import type { MeetingRequest } from '../../types/meetings'

vi.mock('../../lib/api', () => ({
  api: vi.fn(() => Promise.resolve({ ok: false, json: async () => ({}) })),
}))

function makeMeeting(overrides: Partial<MeetingRequest> = {}): MeetingRequest {
  return {
    id: 1,
    initiator_id: 'user-me-uuid',
    target_ids: ['user-other-uuid'],
    duration_minutes: 30,
    context: null,
    status: 'open',
    round: 1,
    agreed_slot: null,
    created_at: '2026-01-01T00:00:00Z',
    updated_at: '2026-01-01T00:00:00Z',
    ...overrides,
  }
}

describe('useMeetingsStore', () => {
  beforeEach(() => {
    setActivePinia(createPinia())
    vi.restoreAllMocks()
  })

  describe('requestMeeting', () => {
    it('posts to /api/meetings/request with correct body', async () => {
      const { api } = await import('../../lib/api')
      const mockApi = vi.mocked(api).mockResolvedValueOnce({
        ok: true,
        status: 201,
        json: async () => ({ id: 42, status: 'open', round: 1 }),
      } as any)

      const { useMeetingsStore } = await import('../meetings')
      const store = useMeetingsStore()
      await store.requestMeeting({
        target_usernames: ['alice'],
        duration_minutes: 30,
        slots: ['2026-05-10T09:00:00Z', '2026-05-10T13:00:00Z'],
        context: 'Sync up',
      })

      expect(mockApi).toHaveBeenCalledWith(
        '/api/meetings/request',
        expect.objectContaining({
          method: 'POST',
          body: JSON.stringify({
            target_usernames: ['alice'],
            duration_minutes: 30,
            slots: ['2026-05-10T09:00:00Z', '2026-05-10T13:00:00Z'],
            context: 'Sync up',
          }),
        }),
      )
    })

    it('adds the new meeting to state on success', async () => {
      const { api } = await import('../../lib/api')
      vi.mocked(api).mockResolvedValueOnce({
        ok: true,
        status: 201,
        json: async () => ({ id: 42, status: 'open', round: 1 }),
      } as any)

      const { useMeetingsStore } = await import('../meetings')
      const store = useMeetingsStore()
      await store.requestMeeting({
        target_usernames: ['alice'],
        duration_minutes: 30,
        slots: ['2026-05-10T09:00:00Z'],
      })

      // After requestMeeting succeeds, pendingByUsername should show alice as having a request
      expect(store.pendingRequestIds).toContain(42)
    })

    it('sets error on API failure', async () => {
      const { api } = await import('../../lib/api')
      vi.mocked(api).mockResolvedValueOnce({
        ok: false,
        status: 400,
        json: async () => ({ detail: 'slots cannot be empty' }),
      } as any)

      const { useMeetingsStore } = await import('../meetings')
      const store = useMeetingsStore()
      await store.requestMeeting({
        target_usernames: ['alice'],
        duration_minutes: 30,
        slots: [],
      })

      expect(store.error).toBeTruthy()
    })

    it('sets loading false after completion', async () => {
      const { api } = await import('../../lib/api')
      vi.mocked(api).mockResolvedValueOnce({
        ok: true,
        status: 201,
        json: async () => ({ id: 1, status: 'open', round: 1 }),
      } as any)

      const { useMeetingsStore } = await import('../meetings')
      const store = useMeetingsStore()
      await store.requestMeeting({
        target_usernames: ['bob'],
        duration_minutes: 60,
        slots: ['2026-05-10T09:00:00Z'],
      })

      expect(store.loading).toBe(false)
    })
  })

  describe('fetchMeetings', () => {
    it('populates meetings from API response', async () => {
      const { api } = await import('../../lib/api')
      const data: MeetingRequest[] = [makeMeeting({ id: 1 }), makeMeeting({ id: 2 })]
      vi.mocked(api).mockResolvedValueOnce({
        ok: true,
        json: async () => data,
      } as any)

      const { useMeetingsStore } = await import('../meetings')
      const store = useMeetingsStore()
      await store.fetchMeetings()

      expect(store.meetings).toHaveLength(2)
      expect(store.loading).toBe(false)
    })

    it('calls GET /api/meetings', async () => {
      const { api } = await import('../../lib/api')
      const mockApi = vi.mocked(api).mockResolvedValueOnce({
        ok: true,
        json: async () => [],
      } as any)

      const { useMeetingsStore } = await import('../meetings')
      const store = useMeetingsStore()
      await store.fetchMeetings()

      expect(mockApi).toHaveBeenCalledWith('/api/meetings', expect.anything())
    })

    it('calls GET /api/meetings?status=open when status filter provided', async () => {
      const { api } = await import('../../lib/api')
      const mockApi = vi.mocked(api).mockResolvedValueOnce({
        ok: true,
        json: async () => [],
      } as any)

      const { useMeetingsStore } = await import('../meetings')
      const store = useMeetingsStore()
      await store.fetchMeetings('open')

      expect(mockApi).toHaveBeenCalledWith('/api/meetings?status=open', expect.anything())
    })

    it('sets error on API failure', async () => {
      const { api } = await import('../../lib/api')
      vi.mocked(api).mockResolvedValueOnce({ ok: false, json: async () => ({}) } as any)

      const { useMeetingsStore } = await import('../meetings')
      const store = useMeetingsStore()
      await store.fetchMeetings()

      expect(store.error).toBeTruthy()
    })
  })

  describe('cancelMeeting', () => {
    it('updates the meeting status to cancelled in state', async () => {
      const { api } = await import('../../lib/api')
      vi.mocked(api).mockResolvedValueOnce({
        ok: true,
        json: async () => ({ id: 1, status: 'cancelled' }),
      } as any)

      const { useMeetingsStore } = await import('../meetings')
      const store = useMeetingsStore()
      store.meetings = [makeMeeting({ id: 1, status: 'open' })]
      await store.cancelMeeting(1)

      expect(store.meetings[0].status).toBe('cancelled')
    })

    it('calls POST /api/meetings/{id}/cancel', async () => {
      const { api } = await import('../../lib/api')
      const mockApi = vi.mocked(api).mockResolvedValueOnce({
        ok: true,
        json: async () => ({ id: 5, status: 'cancelled' }),
      } as any)

      const { useMeetingsStore } = await import('../meetings')
      const store = useMeetingsStore()
      store.meetings = [makeMeeting({ id: 5 })]
      await store.cancelMeeting(5)

      expect(mockApi).toHaveBeenCalledWith(
        '/api/meetings/5/cancel',
        expect.objectContaining({ method: 'POST' }),
      )
    })

    it('sets error on failure', async () => {
      const { api } = await import('../../lib/api')
      vi.mocked(api).mockResolvedValueOnce({ ok: false, json: async () => ({}) } as any)

      const { useMeetingsStore } = await import('../meetings')
      const store = useMeetingsStore()
      store.meetings = [makeMeeting({ id: 1 })]
      await store.cancelMeeting(1)

      expect(store.error).toBeTruthy()
    })
  })

  describe('computed: pendingRequestIds, openMeetings', () => {
    it('pendingRequestIds returns ids of open meetings', async () => {
      const { useMeetingsStore } = await import('../meetings')
      const store = useMeetingsStore()
      store.meetings = [
        makeMeeting({ id: 1, status: 'open' }),
        makeMeeting({ id: 2, status: 'agreed' }),
        makeMeeting({ id: 3, status: 'cancelled' }),
      ]
      expect(store.pendingRequestIds).toEqual([1])
    })

    it('openMeetings returns only open meetings', async () => {
      const { useMeetingsStore } = await import('../meetings')
      const store = useMeetingsStore()
      store.meetings = [
        makeMeeting({ id: 1, status: 'open' }),
        makeMeeting({ id: 2, status: 'agreed' }),
      ]
      expect(store.openMeetings).toHaveLength(1)
      expect(store.openMeetings[0].id).toBe(1)
    })
  })
})
