/**
 * Tests for usePoolWarm composable.
 *
 * Verifies:
 * - Hint is fired when composable is called (mount)
 * - Hint is debounced on rapid agent version changes
 * - Hint fires when agent version changes (after debounce)
 * - Failures are silently swallowed (best-effort)
 */
import { describe, it, expect, vi, beforeEach, afterEach } from 'vitest'
import { setActivePinia, createPinia } from 'pinia'

// Mock the api module
vi.mock('../../lib/api', () => ({
  api: vi.fn(() => Promise.resolve({ ok: true, status: 202, json: async () => ({ hinted: true, options_hash: 'abc123' }) })),
}))

describe('usePoolWarm', () => {
  beforeEach(() => {
    setActivePinia(createPinia())
    vi.clearAllMocks()
    vi.useFakeTimers()
  })

  afterEach(() => {
    vi.useRealTimers()
  })

  it('fires hint POST on initial call', async () => {
    const { api } = await import('../../lib/api')
    const { usePoolWarm } = await import('../usePoolWarm')

    usePoolWarm()

    // Advance debounce timer
    await vi.runAllTimersAsync()

    expect(vi.mocked(api)).toHaveBeenCalledWith(
      '/api/internal/pool/warm',
      expect.objectContaining({ method: 'POST' }),
    )
  })

  it('debounces rapid calls — only fires once for rapid agent changes', async () => {
    const { api } = await import('../../lib/api')
    const { useAgentPickerStore } = await import('../../stores/agentPicker')
    const store = useAgentPickerStore()
    const { usePoolWarm } = await import('../usePoolWarm')

    usePoolWarm()

    // Simulate rapid agent version changes before debounce fires
    store.selectedAgent = 'tether-agent-1.0'
    store.selectedAgent = 'tether-agent-2.0'
    store.selectedAgent = 'tether-agent-2.0'

    // Run timer — debounce should coalesce into one call
    await vi.runAllTimersAsync()

    // Only 1 call total (initial mount hint, debounced)
    expect(vi.mocked(api)).toHaveBeenCalledTimes(1)
  })

  it('fires a new hint after debounce when agent version changes', async () => {
    const { api } = await import('../../lib/api')
    const { useAgentPickerStore } = await import('../../stores/agentPicker')
    const store = useAgentPickerStore()
    const { usePoolWarm } = await import('../usePoolWarm')

    usePoolWarm()

    // First fire (mount)
    await vi.runAllTimersAsync()
    expect(vi.mocked(api)).toHaveBeenCalledTimes(1)

    // Agent version changes → triggers another debounced hint
    store.selectedAgent = 'tether-agent-1.0'
    await vi.runAllTimersAsync()

    expect(vi.mocked(api)).toHaveBeenCalledTimes(2)
  })

  it('swallows API errors silently', async () => {
    const { api } = await import('../../lib/api')
    vi.mocked(api).mockRejectedValueOnce(new Error('network failure'))

    const { usePoolWarm } = await import('../usePoolWarm')

    // Should not throw
    expect(() => usePoolWarm()).not.toThrow()
    await vi.runAllTimersAsync()
    // No unhandled rejection
  })

  it('includes agent_version in POST body', async () => {
    const { api } = await import('../../lib/api')
    const { useAgentPickerStore } = await import('../../stores/agentPicker')
    const store = useAgentPickerStore()
    store.selectedAgent = 'tether-agent-1.0'

    const { usePoolWarm } = await import('../usePoolWarm')
    usePoolWarm()

    await vi.runAllTimersAsync()

    const [, init] = vi.mocked(api).mock.calls[0]
    const body = JSON.parse((init as RequestInit).body as string)
    expect(body.agent_version).toBe('tether-agent-1.0')
  })
})
