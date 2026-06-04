import { describe, it, expect, beforeEach } from 'vitest'
import { mount } from '@vue/test-utils'
import { createPinia, setActivePinia } from 'pinia'
import { vi } from 'vitest'
import StatusIndicator from '../StatusIndicator.vue'
import { useChatStore } from '../../stores/chat'
import { setBotTransport } from '../../composables/useBotTransport'
import { makeTransport } from '../../stores/__tests__/testHelpers'

vi.mock('vue-router', () => ({
  useRouter: () => ({ push: vi.fn() }),
  useRoute: () => ({ path: '/dashboard' }),
}))

describe('StatusIndicator', () => {
  beforeEach(() => {
    setActivePinia(createPinia())
    setBotTransport(makeTransport([]))
  })

  it('renders nothing when currentPhase is null', () => {
    const wrapper = mount(StatusIndicator)
    expect(wrapper.text()).toBe('')
  })

  it('shows "Classifying…" for phase classifier', async () => {
    const store = useChatStore()
    store.currentPhase = 'classifier'
    const wrapper = mount(StatusIndicator)
    await wrapper.vm.$nextTick()
    expect(wrapper.text()).toContain('Classifying…')
  })

  it('shows "Thinking…" for phase main_reasoning', async () => {
    const store = useChatStore()
    store.currentPhase = 'main_reasoning'
    const wrapper = mount(StatusIndicator)
    await wrapper.vm.$nextTick()
    expect(wrapper.text()).toContain('Thinking…')
  })

  it('shows "Using tools…" for phase tool_call', async () => {
    const store = useChatStore()
    store.currentPhase = 'tool_call'
    const wrapper = mount(StatusIndicator)
    await wrapper.vm.$nextTick()
    expect(wrapper.text()).toContain('Using tools…')
  })

  it('shows "Summarizing…" for phase summarization', async () => {
    const store = useChatStore()
    store.currentPhase = 'summarization'
    const wrapper = mount(StatusIndicator)
    await wrapper.vm.$nextTick()
    expect(wrapper.text()).toContain('Summarizing…')
  })

  it('shows statusMessage text when present', async () => {
    const store = useChatStore()
    store.currentPhase = 'main_reasoning'
    store.statusMessage = 'Processing your request...'
    const wrapper = mount(StatusIndicator)
    await wrapper.vm.$nextTick()
    expect(wrapper.text()).toContain('Processing your request...')
  })

  it('does not show statusMessage when currentPhase is null', async () => {
    const store = useChatStore()
    store.currentPhase = null
    store.statusMessage = 'Some message'
    const wrapper = mount(StatusIndicator)
    await wrapper.vm.$nextTick()
    expect(wrapper.text()).toBe('')
  })
})
