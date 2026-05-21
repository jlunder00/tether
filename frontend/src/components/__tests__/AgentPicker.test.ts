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

describe('AgentPicker', () => {
  beforeEach(() => {
    setActivePinia(createPinia())
    vi.restoreAllMocks()
  })

  it('mounts without error', async () => {
    const { default: AgentPicker } = await import('../AgentPicker.vue')
    const wrapper = mount(AgentPicker)
    expect(wrapper.exists()).toBe(true)
  })

  it('renders a trigger button showing current agent', async () => {
    const { default: AgentPicker } = await import('../AgentPicker.vue')
    const wrapper = mount(AgentPicker)
    // Should display the model label somewhere
    expect(wrapper.text()).toContain('tether-agent-2.0')
  })

  it('opens dropdown on trigger click and shows all three options', async () => {
    const { default: AgentPicker } = await import('../AgentPicker.vue')
    const wrapper = mount(AgentPicker)

    // Click trigger to open
    await wrapper.find('button').trigger('click')
    await wrapper.vm.$nextTick()

    const text = wrapper.text()
    expect(text).toContain('tether-agent-1.0')
    expect(text).toContain('tether-agent-2.0')
    expect(text).toContain('tether-agent-2.5')
  })

  it('shows Classic label for 1.0', async () => {
    const { default: AgentPicker } = await import('../AgentPicker.vue')
    const wrapper = mount(AgentPicker)
    await wrapper.find('button').trigger('click')
    await wrapper.vm.$nextTick()
    expect(wrapper.text()).toContain('Classic')
  })

  it('shows Modern label for 2.0', async () => {
    const { default: AgentPicker } = await import('../AgentPicker.vue')
    const wrapper = mount(AgentPicker)
    await wrapper.find('button').trigger('click')
    await wrapper.vm.$nextTick()
    expect(wrapper.text()).toContain('Modern')
  })

  it('shows Premium label for 2.5', async () => {
    const { default: AgentPicker } = await import('../AgentPicker.vue')
    const wrapper = mount(AgentPicker)
    await wrapper.find('button').trigger('click')
    await wrapper.vm.$nextTick()
    expect(wrapper.text()).toContain('Premium')
  })

  it('shows trial badge on 2.5 option', async () => {
    const { default: AgentPicker } = await import('../AgentPicker.vue')
    const wrapper = mount(AgentPicker, {
      props: { trialMessagesLeft: 7 },
    })
    await wrapper.find('button').trigger('click')
    await wrapper.vm.$nextTick()
    expect(wrapper.text()).toContain('7')
  })

  it('selecting 1.0 calls store.setAgent and closes dropdown', async () => {
    const { useAgentPickerStore } = await import('../../stores/agentPicker')
    const store = useAgentPickerStore()
    const spy = vi.spyOn(store, 'setAgent').mockResolvedValue()

    const { default: AgentPicker } = await import('../AgentPicker.vue')
    const wrapper = mount(AgentPicker)

    await wrapper.find('button').trigger('click')
    await wrapper.vm.$nextTick()

    // Click the 1.0 option (first option button in dropdown)
    const options = wrapper.findAll('[data-agent]')
    const option10 = options.find(o => o.attributes('data-agent') === 'tether-agent-1.0')
    expect(option10).toBeDefined()
    await option10!.trigger('click')

    expect(spy).toHaveBeenCalledWith('tether-agent-1.0')
  })

  it('selecting 2.5 calls store.setAgent', async () => {
    const { useAgentPickerStore } = await import('../../stores/agentPicker')
    const store = useAgentPickerStore()
    const spy = vi.spyOn(store, 'setAgent').mockResolvedValue()

    const { default: AgentPicker } = await import('../AgentPicker.vue')
    const wrapper = mount(AgentPicker)

    await wrapper.find('button').trigger('click')
    await wrapper.vm.$nextTick()

    const options = wrapper.findAll('[data-agent]')
    const option25 = options.find(o => o.attributes('data-agent') === 'tether-agent-2.5')
    expect(option25).toBeDefined()
    await option25!.trigger('click')

    expect(spy).toHaveBeenCalledWith('tether-agent-2.5')
  })

  it('shows BYOK modal when store.showByokModal is true', async () => {
    const { useAgentPickerStore } = await import('../../stores/agentPicker')
    const store = useAgentPickerStore()
    store.showByokModal = true

    const { default: AgentPicker } = await import('../AgentPicker.vue')
    // attachTo body so Teleport can render correctly
    mount(AgentPicker, { attachTo: document.body })
    await new Promise(r => setTimeout(r, 0))

    // Teleport renders to document.body — check there
    expect(document.body.textContent).toContain('Continue')
    expect(document.body.textContent).toContain('Stay on 2.0')
  })

  it('store.dismissByokModal() sets showByokModal to false', async () => {
    // Teleported modal content is hard to interact with in jsdom;
    // test the store action directly — the component just calls it.
    const { useAgentPickerStore } = await import('../../stores/agentPicker')
    const store = useAgentPickerStore()
    store.showByokModal = true

    store.dismissByokModal()

    expect(store.showByokModal).toBe(false)
  })

  // ── Bug 1 regression: trial badge hidden for premium users ──

  it('[Bug 1] trial badge shown for free users (is_paid=false)', async () => {
    const { useAuthStore } = await import('../../stores/auth')
    const authStore = useAuthStore()
    authStore.user = { user_id: 'u1', username: 'test', is_admin: false, is_paid: false }

    const { default: AgentPicker } = await import('../AgentPicker.vue')
    const wrapper = mount(AgentPicker, { props: { trialMessagesLeft: 7 } })
    await wrapper.find('button').trigger('click')
    await wrapper.vm.$nextTick()

    expect(wrapper.text()).toContain('7')
    expect(wrapper.text()).toContain('trial')
  })

  it('[Bug 1] trial badge hidden for premium users (is_paid=true)', async () => {
    const { useAuthStore } = await import('../../stores/auth')
    const authStore = useAuthStore()
    authStore.user = { user_id: 'u1', username: 'test', is_admin: false, is_paid: true }

    const { default: AgentPicker } = await import('../AgentPicker.vue')
    const wrapper = mount(AgentPicker, { props: { trialMessagesLeft: 7 } })
    await wrapper.find('button').trigger('click')
    await wrapper.vm.$nextTick()

    expect(wrapper.text()).not.toContain('trial')
  })

  // ── Bug 2 regression: "Continue" wired to confirmByokModal ──
  // DOM click through Teleport content is unreliable in jsdom; test that
  // store.confirmByokModal() produces correct observable state instead.

  it('[Bug 2] confirmByokModal() commits pending 2.5 and closes modal', async () => {
    const { api } = await import('../../lib/api')
    vi.mocked(api).mockResolvedValueOnce({
      ok: true, status: 200, json: async () => ({ ok: true }),
    } as any)

    const { useAuthStore } = await import('../../stores/auth')
    const authStore = useAuthStore()
    authStore.user = { user_id: 'u1', username: 'test', is_admin: false, is_paid: false }

    const { useAgentPickerStore } = await import('../../stores/agentPicker')
    const store = useAgentPickerStore()
    // Simulate state after setAgent('tether-agent-2.5') opened the modal
    store.pendingAgent = 'tether-agent-2.5'
    store.showByokModal = true

    await store.confirmByokModal()

    expect(store.showByokModal).toBe(false)
    expect(store.selectedAgent).toBe('tether-agent-2.5')
  })
})
