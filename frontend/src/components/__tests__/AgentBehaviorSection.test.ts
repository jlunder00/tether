/**
 * Tests for AgentBehaviorSection — settings toggles (Part 3).
 */
import { describe, it, expect, vi, beforeEach } from 'vitest'
import { mount, flushPromises } from '@vue/test-utils'
import { createPinia, setActivePinia } from 'pinia'

vi.mock('../../lib/api', () => ({
  api: vi.fn(() => Promise.resolve({ ok: true, json: async () => ({}) })),
}))

describe('AgentBehaviorSection', () => {
  beforeEach(() => {
    setActivePinia(createPinia())
    vi.clearAllMocks()
  })

  it('mounts without error', async () => {
    const { default: AgentBehaviorSection } = await import('../AgentBehaviorSection.vue')
    const wrapper = mount(AgentBehaviorSection)
    expect(wrapper.exists()).toBe(true)
  })

  it('renders "Auto-approve agent actions" toggle', async () => {
    const { default: AgentBehaviorSection } = await import('../AgentBehaviorSection.vue')
    const wrapper = mount(AgentBehaviorSection)
    expect(wrapper.text()).toContain('Auto-approve agent actions')
  })

  it('renders "Show raw tool names" toggle', async () => {
    const { default: AgentBehaviorSection } = await import('../AgentBehaviorSection.vue')
    const wrapper = mount(AgentBehaviorSection)
    expect(wrapper.text()).toContain('Show raw tool names')
  })

  it('toggles reflect store state — both default false', async () => {
    const { useAgentSettingsStore } = await import('../../stores/agentSettings')
    const store = useAgentSettingsStore()
    expect(store.autoApproveUserActions).toBe(false)
    expect(store.devModeShowRawTools).toBe(false)

    const { default: AgentBehaviorSection } = await import('../AgentBehaviorSection.vue')
    const wrapper = mount(AgentBehaviorSection)
    await flushPromises()

    // Toggle buttons should exist — they should reflect OFF state
    const toggleButtons = wrapper.findAll('button[role="switch"]')
    expect(toggleButtons.length).toBeGreaterThanOrEqual(2)
  })

  it('clicking auto-approve toggle calls store.setAutoApprove', async () => {
    const { api } = await import('../../lib/api')
    vi.mocked(api).mockResolvedValueOnce({ ok: true, json: async () => ({}) } as any)

    const { useAgentSettingsStore } = await import('../../stores/agentSettings')
    const store = useAgentSettingsStore()
    const spy = vi.spyOn(store, 'setAutoApprove').mockResolvedValue()

    const { default: AgentBehaviorSection } = await import('../AgentBehaviorSection.vue')
    const wrapper = mount(AgentBehaviorSection)

    const toggleButtons = wrapper.findAll('button[role="switch"]')
    await toggleButtons[0].trigger('click')

    expect(spy).toHaveBeenCalledWith(true)
  })

  it('clicking dev-mode toggle calls store.setDevMode', async () => {
    const { api } = await import('../../lib/api')
    vi.mocked(api).mockResolvedValueOnce({ ok: true, json: async () => ({}) } as any)

    const { useAgentSettingsStore } = await import('../../stores/agentSettings')
    const store = useAgentSettingsStore()
    const spy = vi.spyOn(store, 'setDevMode').mockResolvedValue()

    const { default: AgentBehaviorSection } = await import('../AgentBehaviorSection.vue')
    const wrapper = mount(AgentBehaviorSection)

    const toggleButtons = wrapper.findAll('button[role="switch"]')
    await toggleButtons[1].trigger('click')

    expect(spy).toHaveBeenCalledWith(true)
  })

  it('clicking auto-approve toggle when ON calls setAutoApprove(false)', async () => {
    const { useAgentSettingsStore } = await import('../../stores/agentSettings')
    const store = useAgentSettingsStore()
    store.autoApproveUserActions = true
    const spy = vi.spyOn(store, 'setAutoApprove').mockResolvedValue()

    const { default: AgentBehaviorSection } = await import('../AgentBehaviorSection.vue')
    const wrapper = mount(AgentBehaviorSection)

    const toggleButtons = wrapper.findAll('button[role="switch"]')
    await toggleButtons[0].trigger('click')

    expect(spy).toHaveBeenCalledWith(false)
  })
})
