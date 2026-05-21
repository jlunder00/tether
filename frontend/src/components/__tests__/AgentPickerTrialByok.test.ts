/**
 * Tests for AgentPicker trial counter and BYOK leakage gate UI (Parts 1 & 2).
 */
import { describe, it, expect, vi, beforeEach } from 'vitest'
import { mount } from '@vue/test-utils'
import { createPinia, setActivePinia } from 'pinia'

vi.mock('vue-router', () => ({
  useRouter: () => ({ push: vi.fn() }),
  useRoute: () => ({ path: '/dashboard' }),
}))

vi.mock('../../lib/api', () => ({
  api: vi.fn(() => Promise.resolve({ ok: true, json: async () => ({}) })),
}))

describe('AgentPicker — Part 1: live trial counter from store', () => {
  beforeEach(() => {
    setActivePinia(createPinia())
    vi.restoreAllMocks()
  })

  it('shows trialMessagesRemaining from store when set', async () => {
    const { useAgentPickerStore } = await import('../../stores/agentPicker')
    const store = useAgentPickerStore()
    store.setTrialRemaining(7)

    const { default: AgentPicker } = await import('../AgentPicker.vue')
    const wrapper = mount(AgentPicker)
    await wrapper.find('button').trigger('click')
    await wrapper.vm.$nextTick()

    expect(wrapper.text()).toContain('7')
    expect(wrapper.text()).toContain('trial')
  })

  it('shows default count when trialMessagesRemaining is null (not yet loaded)', async () => {
    const { useAgentPickerStore } = await import('../../stores/agentPicker')
    const store = useAgentPickerStore()
    // trialMessagesRemaining defaults to null
    expect(store.trialMessagesRemaining).toBeNull()

    const { default: AgentPicker } = await import('../AgentPicker.vue')
    const wrapper = mount(AgentPicker)
    await wrapper.find('button').trigger('click')
    await wrapper.vm.$nextTick()

    // Should still show the trial badge (with fallback value)
    expect(wrapper.text()).toContain('trial')
  })

  it('shows "Upgrade to continue" overlay when trialMessagesRemaining is 0 and user is free', async () => {
    const { useAuthStore } = await import('../../stores/auth')
    const authStore = useAuthStore()
    authStore.user = { user_id: 'u1', username: 'test', is_admin: false, is_paid: false }

    const { useAgentPickerStore } = await import('../../stores/agentPicker')
    const store = useAgentPickerStore()
    store.setTrialRemaining(0)

    const { default: AgentPicker } = await import('../AgentPicker.vue')
    const wrapper = mount(AgentPicker)
    await wrapper.find('button').trigger('click')
    await wrapper.vm.$nextTick()

    expect(wrapper.text()).toContain('Upgrade')
  })

  it('2.5 selection blocked when trialMessagesRemaining is 0 and user is free', async () => {
    const { useAuthStore } = await import('../../stores/auth')
    const authStore = useAuthStore()
    authStore.user = { user_id: 'u1', username: 'test', is_admin: false, is_paid: false }

    const { useAgentPickerStore } = await import('../../stores/agentPicker')
    const store = useAgentPickerStore()
    store.setTrialRemaining(0)
    const spy = vi.spyOn(store, 'setAgent')

    const { default: AgentPicker } = await import('../AgentPicker.vue')
    const wrapper = mount(AgentPicker)
    await wrapper.find('button').trigger('click')
    await wrapper.vm.$nextTick()

    const option25 = wrapper.findAll('[data-agent]').find(o => o.attributes('data-agent') === 'tether-agent-2.5')
    expect(option25).toBeDefined()
    await option25!.trigger('click')

    // Should not call setAgent since 2.5 is locked
    expect(spy).not.toHaveBeenCalled()
  })

  it('premium user sees no trial badge even when trialMessagesRemaining is set', async () => {
    const { useAuthStore } = await import('../../stores/auth')
    const authStore = useAuthStore()
    authStore.user = { user_id: 'u1', username: 'test', is_admin: false, is_paid: true }

    const { useAgentPickerStore } = await import('../../stores/agentPicker')
    const store = useAgentPickerStore()
    store.setTrialRemaining(5)

    const { default: AgentPicker } = await import('../AgentPicker.vue')
    const wrapper = mount(AgentPicker)
    await wrapper.find('button').trigger('click')
    await wrapper.vm.$nextTick()

    expect(wrapper.text()).not.toContain('trial')
  })
})

describe('AgentPicker — Part 2: BYOK leakage gate', () => {
  beforeEach(() => {
    setActivePinia(createPinia())
    vi.restoreAllMocks()
  })

  it('2.5 is shown as disabled with explanation when provider is leaky', async () => {
    const { useAgentPickerStore } = await import('../../stores/agentPicker')
    const store = useAgentPickerStore()
    store.currentProvider = 'openrouter'

    const { default: AgentPicker } = await import('../AgentPicker.vue')
    const wrapper = mount(AgentPicker)
    await wrapper.find('button').trigger('click')
    await wrapper.vm.$nextTick()

    // Should show the disabled/unavailable state text
    const text = wrapper.text()
    expect(text).toContain('Unavailable')
  })

  it('2.5 is not shown as disabled when provider is safe', async () => {
    const { useAgentPickerStore } = await import('../../stores/agentPicker')
    const store = useAgentPickerStore()
    store.currentProvider = 'anthropic_oauth'

    const { default: AgentPicker } = await import('../AgentPicker.vue')
    const wrapper = mount(AgentPicker)
    await wrapper.find('button').trigger('click')
    await wrapper.vm.$nextTick()

    expect(wrapper.text()).not.toContain('Unavailable')
  })

  it('clicking 2.5 does nothing when provider is leaky (no modal, no commit)', async () => {
    const { useAgentPickerStore } = await import('../../stores/agentPicker')
    const store = useAgentPickerStore()
    store.currentProvider = 'openai'
    store.selectedAgent = 'tether-agent-2.0'
    const spy = vi.spyOn(store, 'setAgent')

    const { default: AgentPicker } = await import('../AgentPicker.vue')
    const wrapper = mount(AgentPicker)
    await wrapper.find('button').trigger('click')
    await wrapper.vm.$nextTick()

    const option25 = wrapper.findAll('[data-agent]').find(o => o.attributes('data-agent') === 'tether-agent-2.5')
    await option25!.trigger('click')

    expect(spy).not.toHaveBeenCalled()
    expect(store.selectedAgent).toBe('tether-agent-2.0')
  })
})
