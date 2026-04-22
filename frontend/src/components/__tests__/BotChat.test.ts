import { describe, it, expect, beforeEach, vi } from 'vitest'
import { mount } from '@vue/test-utils'
import { createPinia, setActivePinia } from 'pinia'
import BotChat from '../BotChat.vue'
import { setBotTransport } from '../../composables/useBotTransport'
import type { BotTransport } from '../../composables/useBotTransport'

vi.mock('vue-router', () => ({
  useRouter: () => ({ push: vi.fn() }),
  useRoute: () => ({ path: '/dashboard' }),
}))

const stubTransport: BotTransport = {
  async *send(text: string) { yield `Echo: ${text}` },
  onHeartbeat(cb) { cb(true); return () => {} },
  close: vi.fn(),
}

describe('BotChat', () => {
  beforeEach(() => {
    setActivePinia(createPinia())
    setBotTransport(stubTransport)
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
    // Heartbeat dot should exist — green when alive
    expect(wrapper.find('.rounded-full').exists()).toBe(true)
  })

  it('shows header with Tether label', () => {
    const wrapper = mount(BotChat)
    expect(wrapper.text()).toContain('Tether')
  })
})
