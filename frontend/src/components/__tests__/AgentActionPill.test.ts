import { describe, it, expect, beforeEach } from 'vitest'
import { mount } from '@vue/test-utils'
import { createPinia, setActivePinia } from 'pinia'
import { vi } from 'vitest'
import AgentActionPill from '../AgentActionPill.vue'
import { useChatStore } from '../../stores/chat'
import { setBotTransport } from '../../composables/useBotTransport'
import { makeTransport } from '../../stores/__tests__/testHelpers'

vi.mock('vue-router', () => ({
  useRouter: () => ({ push: vi.fn() }),
  useRoute: () => ({ path: '/dashboard' }),
}))

describe('AgentActionPill', () => {
  beforeEach(() => {
    setActivePinia(createPinia())
    setBotTransport(makeTransport([]))
  })

  it('renders nothing when activeActions map is empty', () => {
    const wrapper = mount(AgentActionPill)
    expect(wrapper.text()).toBe('')
  })

  it('shows a pill when an action with status starting is in the store', async () => {
    const store = useChatStore()
    store.activeActions.set('act1', {
      id: 'act1',
      tool_name: 'reason',
      friendly_text: 'Thinking hard',
      status: 'starting',
    })
    const wrapper = mount(AgentActionPill)
    await wrapper.vm.$nextTick()
    expect(wrapper.text()).toContain('Thinking hard')
  })

  it('shows friendly_text as label', async () => {
    const store = useChatStore()
    store.activeActions.set('act1', {
      id: 'act1',
      tool_name: 'bash',
      friendly_text: 'Running bash command',
      status: 'running',
    })
    const wrapper = mount(AgentActionPill)
    await wrapper.vm.$nextTick()
    expect(wrapper.text()).toContain('Running bash command')
  })

  it('shows spinner indicator for starting status', async () => {
    const store = useChatStore()
    store.activeActions.set('act1', {
      id: 'act1',
      tool_name: 'reason',
      friendly_text: 'Starting up',
      status: 'starting',
    })
    const wrapper = mount(AgentActionPill)
    await wrapper.vm.$nextTick()
    expect(wrapper.find('[data-status="starting"]').exists()).toBe(true)
  })

  it('shows spinner indicator for running status', async () => {
    const store = useChatStore()
    store.activeActions.set('act1', {
      id: 'act1',
      tool_name: 'bash',
      friendly_text: 'Running',
      status: 'running',
    })
    const wrapper = mount(AgentActionPill)
    await wrapper.vm.$nextTick()
    expect(wrapper.find('[data-status="running"]').exists()).toBe(true)
  })

  it('shows checkmark indicator for complete status', async () => {
    const store = useChatStore()
    store.activeActions.set('act1', {
      id: 'act1',
      tool_name: 'reason',
      friendly_text: 'Done thinking',
      status: 'complete',
    })
    const wrapper = mount(AgentActionPill)
    await wrapper.vm.$nextTick()
    expect(wrapper.find('[data-status="complete"]').exists()).toBe(true)
  })

  it('multiple actions render multiple pills', async () => {
    const store = useChatStore()
    store.activeActions.set('act1', {
      id: 'act1',
      tool_name: 'reason',
      friendly_text: 'Thinking',
      status: 'starting',
    })
    store.activeActions.set('act2', {
      id: 'act2',
      tool_name: 'bash',
      friendly_text: 'Running bash',
      status: 'running',
    })
    const wrapper = mount(AgentActionPill)
    await wrapper.vm.$nextTick()
    expect(wrapper.text()).toContain('Thinking')
    expect(wrapper.text()).toContain('Running bash')
    expect(wrapper.findAll('[data-pill]').length).toBe(2)
  })

  it('complete actions have reduced opacity class', async () => {
    const store = useChatStore()
    store.activeActions.set('act1', {
      id: 'act1',
      tool_name: 'reason',
      friendly_text: 'Done',
      status: 'complete',
    })
    const wrapper = mount(AgentActionPill)
    await wrapper.vm.$nextTick()
    const pill = wrapper.find('[data-pill]')
    expect(pill.classes().some(c => c.includes('opacity'))).toBe(true)
  })
})
