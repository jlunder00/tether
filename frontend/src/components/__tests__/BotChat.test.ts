import { describe, it, expect, beforeEach, vi } from 'vitest'
import { mount } from '@vue/test-utils'
import { createPinia, setActivePinia } from 'pinia'
import BotChat from '../BotChat.vue'
import { setBotTransport } from '../../composables/useBotTransport'
import { makeTransport } from '../../stores/__tests__/testHelpers'
import type { WsIncomingEvent } from '../../types/chat'
import { useChatStore } from '../../stores/chat'

vi.mock('vue-router', () => ({
  useRouter: () => ({ push: vi.fn() }),
  useRoute: () => ({ path: '/dashboard' }),
}))

const textEvents: WsIncomingEvent[] = [
  { type: 'agent_text_delta', session_id: 'mock', delta: 'Echo: test' },
  { type: 'turn_complete', session_id: 'mock', final_text: 'Echo: test' },
]

describe('BotChat', () => {
  beforeEach(() => {
    setActivePinia(createPinia())
    setBotTransport(makeTransport(textEvents))
  })

  it('mounts without error', () => {
    const wrapper = mount(BotChat)
    expect(wrapper.exists()).toBe(true)
  })

  it('renders a textarea for input', () => {
    const wrapper = mount(BotChat)
    expect(wrapper.find('textarea').exists()).toBe(true)
  })

  it('renders a send button', () => {
    const wrapper = mount(BotChat)
    expect(wrapper.find('button[type="submit"]').exists()).toBe(true)
  })

  it('send button is disabled when input is empty', () => {
    const wrapper = mount(BotChat)
    const btn = wrapper.find('button[type="submit"]')
    expect((btn.element as HTMLButtonElement).disabled).toBe(true)
  })

  it('shows heartbeat indicator', () => {
    const wrapper = mount(BotChat)
    expect(wrapper.find('.rounded-full').exists()).toBe(true)
  })

  it('shows header with Tether label', () => {
    const wrapper = mount(BotChat)
    expect(wrapper.text()).toContain('Tether')
  })

  it('interrupt button hidden when isSessionActive is false', () => {
    const wrapper = mount(BotChat)
    const store = useChatStore()
    expect(store.isSessionActive).toBe(false)
    expect(wrapper.find('button[aria-label="Interrupt"]').exists()).toBe(false)
  })

  it('interrupt button visible when isSessionActive is true', async () => {
    const wrapper = mount(BotChat)
    const store = useChatStore()
    store.isSessionActive = true
    await wrapper.vm.$nextTick()
    expect(wrapper.find('button[aria-label="Interrupt"]').exists()).toBe(true)
  })

  it('interrupt button click calls chatStore.sendInterrupt', async () => {
    const wrapper = mount(BotChat)
    const store = useChatStore()
    const sendInterruptSpy = vi.spyOn(store, 'sendInterrupt')
    store.isSessionActive = true
    await wrapper.vm.$nextTick()
    await wrapper.find('button[aria-label="Interrupt"]').trigger('click')
    expect(sendInterruptSpy).toHaveBeenCalled()
  })

  it('PermissionModal is rendered', () => {
    const wrapper = mount(BotChat)
    // PermissionModal is included in BotChat — verify it's present
    // (it renders as a Teleport, but the component should be registered)
    expect(wrapper.findComponent({ name: 'PermissionModal' }).exists()).toBe(true)
  })
})
