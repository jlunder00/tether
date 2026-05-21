/**
 * Tests for trial counter (Part 1) and BYOK leakage gate (Part 2) additions
 * to useAgentPickerStore.
 */
import { describe, it, expect, vi, beforeEach } from 'vitest'
import { setActivePinia, createPinia } from 'pinia'
import { setBotTransport } from '../../composables/useBotTransport'
import { makeTransport } from './testHelpers'

vi.mock('../../lib/api', () => ({
  api: vi.fn(() => Promise.resolve({ ok: false, json: async () => ({}) })),
}))

// ─── Part 1: trial counter ───────────────────────────────────────────────────

describe('useAgentPickerStore — trial counter', () => {
  beforeEach(() => {
    setActivePinia(createPinia())
    vi.clearAllMocks()
  })

  it('trialMessagesRemaining defaults to null (not yet loaded)', async () => {
    const { useAgentPickerStore } = await import('../agentPicker')
    const store = useAgentPickerStore()
    expect(store.trialMessagesRemaining).toBeNull()
  })

  it('setTrialRemaining updates trialMessagesRemaining', async () => {
    const { useAgentPickerStore } = await import('../agentPicker')
    const store = useAgentPickerStore()
    store.setTrialRemaining(5)
    expect(store.trialMessagesRemaining).toBe(5)
  })

  it('setTrialRemaining(0) sets count to 0', async () => {
    const { useAgentPickerStore } = await import('../agentPicker')
    const store = useAgentPickerStore()
    store.setTrialRemaining(0)
    expect(store.trialMessagesRemaining).toBe(0)
  })
})

// ─── Part 1: chat store forwards trial_usage_update ──────────────────────────

describe('useChatStore — trial_usage_update updates agentPicker', () => {
  beforeEach(() => {
    setActivePinia(createPinia())
    vi.clearAllMocks()
  })

  it('trial_usage_update event updates agentPickerStore.trialMessagesRemaining', async () => {
    setBotTransport(makeTransport([
      { type: 'trial_usage_update', session_id: 'sess1', remaining: 3 },
      { type: 'turn_complete', session_id: 'sess1', final_text: '' },
    ]))

    const { useChatStore } = await import('../chat')
    const { useAgentPickerStore } = await import('../agentPicker')
    const chatStore = useChatStore()
    const pickerStore = useAgentPickerStore()

    await chatStore.send('hi')

    expect(pickerStore.trialMessagesRemaining).toBe(3)
  })

  it('multiple trial_usage_update events keep the last value', async () => {
    setBotTransport(makeTransport([
      { type: 'trial_usage_update', session_id: 'sess1', remaining: 5 },
      { type: 'trial_usage_update', session_id: 'sess1', remaining: 4 },
      { type: 'turn_complete', session_id: 'sess1', final_text: 'done' },
    ]))

    const { useChatStore } = await import('../chat')
    const { useAgentPickerStore } = await import('../agentPicker')
    const chatStore = useChatStore()
    const pickerStore = useAgentPickerStore()

    await chatStore.send('hi')

    expect(pickerStore.trialMessagesRemaining).toBe(4)
  })
})

// ─── Part 2: BYOK leakage gate ───────────────────────────────────────────────

describe('useAgentPickerStore — BYOK leakage gate', () => {
  beforeEach(() => {
    setActivePinia(createPinia())
    vi.clearAllMocks()
  })

  it('currentProvider defaults to anthropic_oauth', async () => {
    const { useAgentPickerStore } = await import('../agentPicker')
    const store = useAgentPickerStore()
    expect(store.currentProvider).toBe('anthropic_oauth')
  })

  it('isLeakyProvider is false for anthropic_oauth', async () => {
    const { useAgentPickerStore } = await import('../agentPicker')
    const store = useAgentPickerStore()
    expect(store.isLeakyProvider).toBe(false)
  })

  it('isLeakyProvider is true for openrouter', async () => {
    const { useAgentPickerStore } = await import('../agentPicker')
    const store = useAgentPickerStore()
    store.currentProvider = 'openrouter'
    expect(store.isLeakyProvider).toBe(true)
  })

  it('isLeakyProvider is true for openai', async () => {
    const { useAgentPickerStore } = await import('../agentPicker')
    const store = useAgentPickerStore()
    store.currentProvider = 'openai'
    expect(store.isLeakyProvider).toBe(true)
  })

  it('isLeakyProvider is false for anthropic_api', async () => {
    const { useAgentPickerStore } = await import('../agentPicker')
    const store = useAgentPickerStore()
    store.currentProvider = 'anthropic_api'
    expect(store.isLeakyProvider).toBe(false)
  })

  it('setAgent 2.5 is blocked when provider is leaky — no modal opened, agent unchanged', async () => {
    const { useAgentPickerStore } = await import('../agentPicker')
    const store = useAgentPickerStore()
    store.currentProvider = 'openrouter'
    store.selectedAgent = 'tether-agent-2.0'

    await store.setAgent('tether-agent-2.5')

    expect(store.selectedAgent).toBe('tether-agent-2.0')
    expect(store.showByokModal).toBe(false)
  })
})
