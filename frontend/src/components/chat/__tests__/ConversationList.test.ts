import { describe, it, expect, vi, beforeEach } from 'vitest'
import { mount, flushPromises } from '@vue/test-utils'
import { setActivePinia, createPinia } from 'pinia'
import { reactive, ref } from 'vue'

vi.mock('../../../stores/conversations', () => ({
  useConversationsStore: vi.fn(),
}))

import { useConversationsStore } from '../../../stores/conversations'
import ConversationList from '../ConversationList.vue'

const mockUseConversationsStore = vi.mocked(useConversationsStore)

function makeConv(overrides = {}) {
  return {
    id: 'conv-1',
    name: 'Test Conv',
    type: 'interactive' as const,
    priority: 'normal' as const,
    state: 'open' as const,
    context_node_id: null,
    thread_key: null,
    is_system: false,
    created_at: '2026-01-01T00:00:00Z',
    last_message_at: '2026-01-01T00:01:00Z',
    folder_name: null,
    ...overrides,
  }
}

function makeStore(convs: ReturnType<typeof makeConv>[] = []) {
  return reactive({
    list: convs,
    selectedId: ref<string | null>(null),
    loading: false,
    error: null,
    refresh: vi.fn().mockResolvedValue(undefined),
    select: vi.fn(),
    create: vi.fn().mockResolvedValue(null),
  })
}

describe('ConversationList', () => {
  beforeEach(() => {
    setActivePinia(createPinia())
    vi.clearAllMocks()
  })

  it('accepts activeNodeId prop (string | null, default null)', () => {
    const store = makeStore()
    mockUseConversationsStore.mockReturnValue(store as any)

    // Should mount with no prop (default null)
    const wrapper = mount(ConversationList)
    expect(wrapper.exists()).toBe(true)

    // Should also accept a string
    const wrapper2 = mount(ConversationList, {
      props: { activeNodeId: 'node-1' },
    })
    expect(wrapper2.exists()).toBe(true)
  })

  it('calls store.refresh with context_node_id when activeNodeId prop is set on mount', async () => {
    const store = makeStore()
    mockUseConversationsStore.mockReturnValue(store as any)

    mount(ConversationList, {
      props: { activeNodeId: 'node-abc' },
    })
    await flushPromises()

    // Called at least once with the node id
    const calls = store.refresh.mock.calls
    const nodeCall = calls.find((c: any[]) => c[0]?.context_node_id === 'node-abc')
    expect(nodeCall).toBeTruthy()
  })

  it('calls store.refresh with context_node_id when activeNodeId prop changes to a node', async () => {
    const store = makeStore()
    mockUseConversationsStore.mockReturnValue(store as any)

    const wrapper = mount(ConversationList, {
      props: { activeNodeId: null },
    })
    await flushPromises()
    store.refresh.mockClear()

    await wrapper.setProps({ activeNodeId: 'node-xyz' })
    await flushPromises()

    // buildRefreshParams composes both filters; with activeFilter='all', only context_node_id is set
    expect(store.refresh).toHaveBeenCalledWith({ context_node_id: 'node-xyz' })
  })

  it('calls store.refresh without context_node_id when activeNodeId changes back to null', async () => {
    const store = makeStore()
    mockUseConversationsStore.mockReturnValue(store as any)

    const wrapper = mount(ConversationList, {
      props: { activeNodeId: 'node-1' },
    })
    await flushPromises()
    store.refresh.mockClear()

    await wrapper.setProps({ activeNodeId: null })
    await flushPromises()

    // With no active state filter and no node filter, buildRefreshParams returns undefined
    expect(store.refresh).toHaveBeenCalledWith(undefined)
  })

  it('conversation rows have draggable="true"', () => {
    const store = makeStore([makeConv(), makeConv({ id: 'conv-2', name: 'Conv 2' })])
    mockUseConversationsStore.mockReturnValue(store as any)

    const wrapper = mount(ConversationList)

    const rows = wrapper.findAll('[data-testid="conversation-row"]')
    expect(rows.length).toBeGreaterThan(0)
    rows.forEach(row => {
      expect(row.attributes('draggable')).toBe('true')
    })
  })

  it('sets dataTransfer with conversationId on dragstart', async () => {
    const convs = [makeConv({ id: 'conv-99', name: 'Draggable Conv' })]
    const store = makeStore(convs)
    mockUseConversationsStore.mockReturnValue(store as any)

    const wrapper = mount(ConversationList)

    const row = wrapper.find('[data-testid="conversation-row"]')
    expect(row.exists()).toBe(true)

    const setDataMock = vi.fn()
    const dragEvent = new Event('dragstart') as any
    dragEvent.dataTransfer = { setData: setDataMock }

    await row.element.dispatchEvent(dragEvent)
    await wrapper.vm.$nextTick()

    expect(setDataMock).toHaveBeenCalledWith(
      'text/plain',
      JSON.stringify({ conversationId: 'conv-99' })
    )
  })
})
