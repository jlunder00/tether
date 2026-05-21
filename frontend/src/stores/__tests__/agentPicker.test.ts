import { describe, it, expect, vi, beforeEach } from 'vitest'
import { setActivePinia, createPinia } from 'pinia'

vi.mock('../../lib/api', () => ({
  api: vi.fn(() => Promise.resolve({ ok: false, json: async () => ({}) })),
}))

describe('useAgentPickerStore', () => {
  beforeEach(() => {
    setActivePinia(createPinia())
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

  it('setAgent updates selectedAgent and calls PUT /api/settings/preferred_agent_version', async () => {
    const { api } = await import('../../lib/api')
    vi.mocked(api).mockResolvedValueOnce({
      ok: true,
      status: 200,
      json: async () => ({ ok: true }),
    } as any)

    const { useAgentPickerStore } = await import('../agentPicker')
    const store = useAgentPickerStore()
    await store.setAgent('tether-agent-2.5')

    expect(store.selectedAgent).toBe('tether-agent-2.5')
    expect(vi.mocked(api)).toHaveBeenCalledWith(
      '/api/settings/preferred_agent_version',
      expect.objectContaining({
        method: 'PUT',
        body: JSON.stringify({ value: 'tether-agent-2.5' }),
      }),
    )
  })

  it('setAgent keeps previous value on API failure', async () => {
    const { api } = await import('../../lib/api')
    vi.mocked(api).mockResolvedValueOnce({
      ok: false,
      status: 500,
      json: async () => ({}),
    } as any)

    const { useAgentPickerStore } = await import('../agentPicker')
    const store = useAgentPickerStore()
    // pre-seed a non-default value
    store.selectedAgent = 'tether-agent-1.0'
    await store.setAgent('tether-agent-2.5')

    // should roll back
    expect(store.selectedAgent).toBe('tether-agent-1.0')
  })

  it('showByokModal is false initially', async () => {
    const { useAgentPickerStore } = await import('../agentPicker')
    const store = useAgentPickerStore()
    expect(store.showByokModal).toBe(false)
  })

  it('setAgent triggers showByokModal for 2.5 selection', async () => {
    const { api } = await import('../../lib/api')
    vi.mocked(api).mockResolvedValueOnce({
      ok: true,
      status: 200,
      json: async () => ({ ok: true }),
    } as any)

    const { useAgentPickerStore } = await import('../agentPicker')
    const store = useAgentPickerStore()
    await store.setAgent('tether-agent-2.5')

    expect(store.showByokModal).toBe(true)
  })

  it('dismissByokModal sets showByokModal false', async () => {
    const { useAgentPickerStore } = await import('../agentPicker')
    const store = useAgentPickerStore()
    store.showByokModal = true
    store.dismissByokModal()
    expect(store.showByokModal).toBe(false)
  })
})
