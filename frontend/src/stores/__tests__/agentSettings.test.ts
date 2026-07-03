/**
 * Tests for useAgentSettingsStore — auto-approve + dev_mode toggles (Part 3).
 */
import { describe, it, expect, vi, beforeEach } from 'vitest'
import { setActivePinia, createPinia } from 'pinia'

vi.mock('../../lib/api', () => ({
  api: vi.fn(() => Promise.resolve({ ok: true, json: async () => ({}) })),
}))

describe('useAgentSettingsStore', () => {
  beforeEach(() => {
    setActivePinia(createPinia())
    vi.clearAllMocks()
  })

  it('autoApproveUserActions defaults to false', async () => {
    const { useAgentSettingsStore } = await import('../agentSettings')
    const store = useAgentSettingsStore()
    expect(store.autoApproveUserActions).toBe(false)
  })

  it('devModeShowRawTools defaults to false', async () => {
    const { useAgentSettingsStore } = await import('../agentSettings')
    const store = useAgentSettingsStore()
    expect(store.devModeShowRawTools).toBe(false)
  })

  it('fetchSettings loads autoApproveUserActions from API', async () => {
    const { api } = await import('../../lib/api')
    vi.mocked(api).mockResolvedValueOnce({
      ok: true,
      json: async () => ({
        auto_approve_user_actions: 'true',
        dev_mode_show_raw_tools: 'false',
      }),
    } as any)

    const { useAgentSettingsStore } = await import('../agentSettings')
    const store = useAgentSettingsStore()
    await store.fetchSettings()

    expect(store.autoApproveUserActions).toBe(true)
  })

  it('fetchSettings loads devModeShowRawTools from API', async () => {
    const { api } = await import('../../lib/api')
    vi.mocked(api).mockResolvedValueOnce({
      ok: true,
      json: async () => ({
        auto_approve_user_actions: 'false',
        dev_mode_show_raw_tools: 'true',
      }),
    } as any)

    const { useAgentSettingsStore } = await import('../agentSettings')
    const store = useAgentSettingsStore()
    await store.fetchSettings()

    expect(store.devModeShowRawTools).toBe(true)
  })

  it('fetchSettings keeps defaults when API fails', async () => {
    const { api } = await import('../../lib/api')
    vi.mocked(api).mockResolvedValueOnce({ ok: false, json: async () => ({}) } as any)

    const { useAgentSettingsStore } = await import('../agentSettings')
    const store = useAgentSettingsStore()
    await store.fetchSettings()

    expect(store.autoApproveUserActions).toBe(false)
    expect(store.devModeShowRawTools).toBe(false)
  })

  it('setAutoApprove(true) PUTs to /api/settings/auto_approve_user_actions', async () => {
    const { api } = await import('../../lib/api')
    vi.mocked(api).mockResolvedValueOnce({ ok: true, json: async () => ({}) } as any)

    const { useAgentSettingsStore } = await import('../agentSettings')
    const store = useAgentSettingsStore()
    await store.setAutoApprove(true)

    expect(vi.mocked(api)).toHaveBeenCalledWith(
      '/api/settings/auto_approve_user_actions',
      expect.objectContaining({
        method: 'PUT',
        body: JSON.stringify({ value: 'true' }),
      }),
    )
    expect(store.autoApproveUserActions).toBe(true)
  })

  it('setAutoApprove(false) PUTs false value', async () => {
    const { api } = await import('../../lib/api')
    vi.mocked(api).mockResolvedValueOnce({ ok: true, json: async () => ({}) } as any)

    const { useAgentSettingsStore } = await import('../agentSettings')
    const store = useAgentSettingsStore()
    store.autoApproveUserActions = true
    await store.setAutoApprove(false)

    expect(store.autoApproveUserActions).toBe(false)
  })

  it('setAutoApprove rolls back on API failure', async () => {
    const { api } = await import('../../lib/api')
    vi.mocked(api).mockResolvedValueOnce({ ok: false, json: async () => ({}) } as any)

    const { useAgentSettingsStore } = await import('../agentSettings')
    const store = useAgentSettingsStore()
    store.autoApproveUserActions = false
    await store.setAutoApprove(true)

    expect(store.autoApproveUserActions).toBe(false)
  })

  it('setDevMode(true) PUTs to /api/settings/dev_mode_show_raw_tools', async () => {
    const { api } = await import('../../lib/api')
    vi.mocked(api).mockResolvedValueOnce({ ok: true, json: async () => ({}) } as any)

    const { useAgentSettingsStore } = await import('../agentSettings')
    const store = useAgentSettingsStore()
    await store.setDevMode(true)

    expect(vi.mocked(api)).toHaveBeenCalledWith(
      '/api/settings/dev_mode_show_raw_tools',
      expect.objectContaining({
        method: 'PUT',
        body: JSON.stringify({ value: 'true' }),
      }),
    )
    expect(store.devModeShowRawTools).toBe(true)
  })

  it('setDevMode rolls back on API failure', async () => {
    const { api } = await import('../../lib/api')
    vi.mocked(api).mockResolvedValueOnce({ ok: false, json: async () => ({}) } as any)

    const { useAgentSettingsStore } = await import('../agentSettings')
    const store = useAgentSettingsStore()
    store.devModeShowRawTools = false
    await store.setDevMode(true)

    expect(store.devModeShowRawTools).toBe(false)
  })
})
