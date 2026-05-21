import { describe, it, expect, vi, beforeEach } from 'vitest'
import { setActivePinia, createPinia } from 'pinia'

vi.mock('../../lib/api', () => ({
  api: vi.fn(() => Promise.resolve({ ok: false, json: async () => ({}) })),
}))

// Helper: seed the auth store's user value without triggering any fetches
async function setAuthUser(opts: { is_paid?: boolean } = {}) {
  const { useAuthStore } = await import('../auth')
  const store = useAuthStore()
  store.user = {
    user_id: 'test-user',
    username: 'testuser',
    is_admin: false,
    is_paid: opts.is_paid ?? false,
  }
  return store
}

describe('useAgentPickerStore', () => {
  beforeEach(() => {
    setActivePinia(createPinia())
    vi.clearAllMocks()   // clear call history on vi.fn() mocks (restoreAllMocks only resets spies)
    vi.restoreAllMocks()
  })

  it('defaults selectedAgent to tether-agent-2.0', async () => {
    const { useAgentPickerStore } = await import('../agentPicker')
    const store = useAgentPickerStore()
    expect(store.selectedAgent).toBe('tether-agent-2.0')
  })

  it('fetchPreference loads value from API and updates selectedAgent', async () => {
    const { api } = await import('../../lib/api')
    vi.mocked(api).mockResolvedValueOnce({
      ok: true,
      status: 200,
      json: async () => ({ preferred_agent_version: 'tether-agent-1.0' }),
    } as any)

    const { useAgentPickerStore } = await import('../agentPicker')
    const store = useAgentPickerStore()
    await store.fetchPreference()

    expect(store.selectedAgent).toBe('tether-agent-1.0')
  })

  it('fetchPreference keeps 2.0 default when API returns missing key', async () => {
    const { api } = await import('../../lib/api')
    vi.mocked(api).mockResolvedValueOnce({
      ok: true,
      status: 200,
      json: async () => ({}),
    } as any)

    const { useAgentPickerStore } = await import('../agentPicker')
    const store = useAgentPickerStore()
    await store.fetchPreference()

    expect(store.selectedAgent).toBe('tether-agent-2.0')
  })

  it('fetchPreference keeps 2.0 default on API failure', async () => {
    const { api } = await import('../../lib/api')
    vi.mocked(api).mockResolvedValueOnce({
      ok: false,
      status: 500,
      json: async () => ({}),
    } as any)

    const { useAgentPickerStore } = await import('../agentPicker')
    const store = useAgentPickerStore()
    await store.fetchPreference()

    expect(store.selectedAgent).toBe('tether-agent-2.0')
  })

  it('setAgent 1.0 commits immediately without modal', async () => {
    const { api } = await import('../../lib/api')
    vi.mocked(api).mockResolvedValueOnce({
      ok: true,
      status: 200,
      json: async () => ({ ok: true }),
    } as any)

    const { useAgentPickerStore } = await import('../agentPicker')
    const store = useAgentPickerStore()
    await store.setAgent('tether-agent-1.0')

    expect(store.selectedAgent).toBe('tether-agent-1.0')
    expect(store.showByokModal).toBe(false)
    expect(vi.mocked(api)).toHaveBeenCalledWith(
      '/api/settings/preferred_agent_version',
      expect.objectContaining({ method: 'PUT' }),
    )
  })

  it('setAgent 2.0 commits immediately without modal', async () => {
    const { api } = await import('../../lib/api')
    vi.mocked(api).mockResolvedValueOnce({
      ok: true, status: 200, json: async () => ({ ok: true }),
    } as any)

    const { useAgentPickerStore } = await import('../agentPicker')
    const store = useAgentPickerStore()
    store.selectedAgent = 'tether-agent-1.0'
    await store.setAgent('tether-agent-2.0')

    expect(store.selectedAgent).toBe('tether-agent-2.0')
    expect(store.showByokModal).toBe(false)
  })

  it('setAgent keeps previous value on API failure for non-2.5', async () => {
    const { api } = await import('../../lib/api')
    vi.mocked(api).mockResolvedValueOnce({
      ok: false, status: 500, json: async () => ({}),
    } as any)

    const { useAgentPickerStore } = await import('../agentPicker')
    const store = useAgentPickerStore()
    store.selectedAgent = 'tether-agent-1.0'
    await store.setAgent('tether-agent-2.0')

    expect(store.selectedAgent).toBe('tether-agent-1.0')
  })

  // ── Bug 2 regression: modal is a confirmation gate, not a post-commit overlay ──

  it('[Bug 2] setAgent 2.5 on free user shows modal and does NOT call API', async () => {
    const { api } = await import('../../lib/api')
    await setAuthUser({ is_paid: false })

    const { useAgentPickerStore } = await import('../agentPicker')
    const store = useAgentPickerStore()
    await store.setAgent('tether-agent-2.5')

    expect(store.showByokModal).toBe(true)
    expect(store.selectedAgent).toBe('tether-agent-2.0')  // unchanged
    expect(vi.mocked(api)).not.toHaveBeenCalled()         // API not touched yet
  })

  it('[Bug 2] confirmByokModal commits 2.5 via API and closes modal', async () => {
    const { api } = await import('../../lib/api')
    vi.mocked(api).mockResolvedValueOnce({
      ok: true, status: 200, json: async () => ({ ok: true }),
    } as any)
    await setAuthUser({ is_paid: false })

    const { useAgentPickerStore } = await import('../agentPicker')
    const store = useAgentPickerStore()
    await store.setAgent('tether-agent-2.5')  // opens modal, no commit
    await store.confirmByokModal()            // user clicked "Continue"

    expect(store.selectedAgent).toBe('tether-agent-2.5')
    expect(store.showByokModal).toBe(false)
    expect(vi.mocked(api)).toHaveBeenCalledWith(
      '/api/settings/preferred_agent_version',
      expect.objectContaining({
        method: 'PUT',
        body: JSON.stringify({ value: 'tether-agent-2.5' }),
      }),
    )
  })

  it('[Bug 2] cancelByokModal closes modal without changing selectedAgent', async () => {
    const { api } = await import('../../lib/api')
    await setAuthUser({ is_paid: false })

    const { useAgentPickerStore } = await import('../agentPicker')
    const store = useAgentPickerStore()
    store.selectedAgent = 'tether-agent-1.0'
    await store.setAgent('tether-agent-2.5')  // opens modal
    store.cancelByokModal()                   // user clicked "Stay on 2.0"

    expect(store.selectedAgent).toBe('tether-agent-1.0')  // unchanged
    expect(store.showByokModal).toBe(false)
    expect(vi.mocked(api)).not.toHaveBeenCalled()
  })

  it('[Bug 2] confirmByokModal rollback if API fails — modal closes, selection unchanged', async () => {
    const { api } = await import('../../lib/api')
    vi.mocked(api).mockResolvedValueOnce({
      ok: false, status: 500, json: async () => ({}),
    } as any)
    await setAuthUser({ is_paid: false })

    const { useAgentPickerStore } = await import('../agentPicker')
    const store = useAgentPickerStore()
    store.selectedAgent = 'tether-agent-1.0'
    await store.setAgent('tether-agent-2.5')
    await store.confirmByokModal()

    expect(store.selectedAgent).toBe('tether-agent-1.0')  // rolled back
    expect(store.showByokModal).toBe(false)
  })

  // ── Bug 1 regression: premium users bypass modal and trial badge ──

  it('[Bug 1] setAgent 2.5 on premium user commits directly — no modal', async () => {
    const { api } = await import('../../lib/api')
    vi.mocked(api).mockResolvedValueOnce({
      ok: true, status: 200, json: async () => ({ ok: true }),
    } as any)
    await setAuthUser({ is_paid: true })

    const { useAgentPickerStore } = await import('../agentPicker')
    const store = useAgentPickerStore()
    await store.setAgent('tether-agent-2.5')

    expect(store.selectedAgent).toBe('tether-agent-2.5')
    expect(store.showByokModal).toBe(false)
    expect(vi.mocked(api)).toHaveBeenCalled()
  })

  it('showByokModal is false initially', async () => {
    const { useAgentPickerStore } = await import('../agentPicker')
    const store = useAgentPickerStore()
    expect(store.showByokModal).toBe(false)
  })
})
