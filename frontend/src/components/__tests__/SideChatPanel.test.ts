import { describe, it, expect, beforeEach, vi } from 'vitest'
import { mount } from '@vue/test-utils'
import { createPinia, setActivePinia } from 'pinia'

vi.mock('vue-router', () => ({
  useRouter: () => ({ push: vi.fn() }),
  useRoute: () => ({ path: '/chat' }),
  RouterLink: { props: ['to', 'activeClass'], template: '<a :href="to"><slot /></a>' },
  RouterView: { template: '<div />' },
}))

vi.mock('../../lib/api', () => ({
  api: vi.fn(() => Promise.resolve({ ok: true, json: async () => [] })),
}))

describe('SideChatPanel', () => {
  beforeEach(() => {
    setActivePinia(createPinia())
    vi.clearAllMocks()
  })

  it('mounts without error', async () => {
    const { default: SideChatPanel } = await import('../SideChatPanel.vue')
    const wrapper = mount(SideChatPanel)
    expect(wrapper.exists()).toBe(true)
  })

  it('emits close when close button is clicked', async () => {
    const { default: SideChatPanel } = await import('../SideChatPanel.vue')
    const wrapper = mount(SideChatPanel)
    await wrapper.find('button[aria-label="Close chat panel"]').trigger('click')
    expect(wrapper.emitted('close')).toBeTruthy()
    expect(wrapper.emitted('close')!.length).toBe(1)
  })

  it('emits close when Escape key is pressed', async () => {
    const { default: SideChatPanel } = await import('../SideChatPanel.vue')
    const wrapper = mount(SideChatPanel)
    await wrapper.trigger('keydown', { key: 'Escape' })
    expect(wrapper.emitted('close')).toBeTruthy()
  })

  it('renders ConversationList component', async () => {
    const { default: SideChatPanel } = await import('../SideChatPanel.vue')
    const wrapper = mount(SideChatPanel)
    expect(wrapper.findComponent({ name: 'ConversationList' }).exists()).toBe(true)
  })

  it('renders ConversationView component', async () => {
    const { default: SideChatPanel } = await import('../SideChatPanel.vue')
    const wrapper = mount(SideChatPanel)
    expect(wrapper.findComponent({ name: 'ConversationView' }).exists()).toBe(true)
  })

  it('shows the "Chat" heading', async () => {
    const { default: SideChatPanel } = await import('../SideChatPanel.vue')
    const wrapper = mount(SideChatPanel)
    expect(wrapper.text()).toContain('Chat')
  })
})
