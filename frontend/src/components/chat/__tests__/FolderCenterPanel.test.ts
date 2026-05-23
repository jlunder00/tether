import { describe, it, expect, vi, beforeEach } from 'vitest'
import { mount, flushPromises } from '@vue/test-utils'
import { setActivePinia, createPinia } from 'pinia'
import { reactive, ref, computed } from 'vue'

vi.mock('../../../stores/conversations', () => ({
  useConversationsStore: vi.fn(),
}))
vi.mock('../../../stores/context', () => ({
  useContextStore: vi.fn(),
}))

import { useConversationsStore } from '../../../stores/conversations'
import { useContextStore } from '../../../stores/context'

const mockUseConversationsStore = vi.mocked(useConversationsStore)
const mockUseContextStore = vi.mocked(useContextStore)

function makeConv(overrides = {}) {
  return {
    id: 'conv-1',
    name: 'Test Conv',
    type: 'interactive' as const,
    priority: 'normal' as const,
    state: 'open' as const,
    context_node_id: 'node-1',
    thread_key: null,
    is_system: false,
    created_at: '2026-01-01T00:00:00Z',
    last_message_at: '2026-01-01T00:01:00Z',
    folder_name: 'Test Node',
    ...overrides,
  }
}

function makeConvStore(convs: ReturnType<typeof makeConv>[] = []) {
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

function makeContextStore(nodesMap: Record<string, any> = {}) {
  return reactive({
    nodes: nodesMap,
    rootNodes: computed(() => []),
    fetchRootNodes: vi.fn().mockResolvedValue([]),
    fetchChildren: vi.fn().mockResolvedValue([]),
    childrenOf: vi.fn().mockReturnValue([]),
  })
}

describe('FolderCenterPanel', () => {
  beforeEach(() => {
    setActivePinia(createPinia())
    vi.clearAllMocks()
  })

  it('mounts without error', async () => {
    mockUseConversationsStore.mockReturnValue(makeConvStore() as any)
    mockUseContextStore.mockReturnValue(makeContextStore() as any)

    const { default: FolderCenterPanel } = await import('../FolderCenterPanel.vue')
    const wrapper = mount(FolderCenterPanel, {
      props: { nodeId: null },
    })
    expect(wrapper.exists()).toBe(true)
  })

  it('calls convStore.refresh with context_node_id when nodeId prop is set on mount', async () => {
    const store = makeConvStore()
    mockUseConversationsStore.mockReturnValue(store as any)
    mockUseContextStore.mockReturnValue(makeContextStore() as any)

    const { default: FolderCenterPanel } = await import('../FolderCenterPanel.vue')
    mount(FolderCenterPanel, { props: { nodeId: 'node-1' } })
    await flushPromises()

    expect(store.refresh).toHaveBeenCalledWith({ context_node_id: 'node-1' })
  })

  it('calls convStore.refresh when nodeId prop changes', async () => {
    const store = makeConvStore()
    mockUseConversationsStore.mockReturnValue(store as any)
    mockUseContextStore.mockReturnValue(makeContextStore() as any)

    const { default: FolderCenterPanel } = await import('../FolderCenterPanel.vue')
    const wrapper = mount(FolderCenterPanel, { props: { nodeId: null } })
    await flushPromises()
    store.refresh.mockClear()

    await wrapper.setProps({ nodeId: 'node-abc' })
    await flushPromises()

    expect(store.refresh).toHaveBeenCalledWith({ context_node_id: 'node-abc' })
  })

  it('shows only conversations matching nodeId prop', async () => {
    const convs = [
      makeConv({ id: 'conv-1', context_node_id: 'node-1', name: 'In Node 1' }),
      makeConv({ id: 'conv-2', context_node_id: 'node-2', name: 'In Node 2' }),
    ]
    mockUseConversationsStore.mockReturnValue(makeConvStore(convs) as any)
    mockUseContextStore.mockReturnValue(makeContextStore() as any)

    const { default: FolderCenterPanel } = await import('../FolderCenterPanel.vue')
    const wrapper = mount(FolderCenterPanel, { props: { nodeId: 'node-1' } })

    expect(wrapper.text()).toContain('In Node 1')
    expect(wrapper.text()).not.toContain('In Node 2')
  })

  it('shows empty state when no conversations match nodeId', async () => {
    mockUseConversationsStore.mockReturnValue(makeConvStore() as any)
    mockUseContextStore.mockReturnValue(makeContextStore() as any)

    const { default: FolderCenterPanel } = await import('../FolderCenterPanel.vue')
    const wrapper = mount(FolderCenterPanel, { props: { nodeId: 'node-1' } })

    expect(wrapper.text()).toContain('No conversations yet')
  })

  it('renders breadcrumb path from contextStore.nodes', async () => {
    const nodesMap = {
      'node-parent': { id: 'node-parent', parent_id: null, name: 'Parent' },
      'node-child': { id: 'node-child', parent_id: 'node-parent', name: 'Child' },
    }
    mockUseConversationsStore.mockReturnValue(makeConvStore() as any)
    mockUseContextStore.mockReturnValue(makeContextStore(nodesMap) as any)

    const { default: FolderCenterPanel } = await import('../FolderCenterPanel.vue')
    const wrapper = mount(FolderCenterPanel, { props: { nodeId: 'node-child' } })

    expect(wrapper.text()).toContain('Parent')
    expect(wrapper.text()).toContain('Child')
  })

  it('emits open-conversation when conversation row is clicked', async () => {
    const convs = [makeConv({ id: 'conv-1', context_node_id: 'node-1' })]
    mockUseConversationsStore.mockReturnValue(makeConvStore(convs) as any)
    mockUseContextStore.mockReturnValue(makeContextStore() as any)

    const { default: FolderCenterPanel } = await import('../FolderCenterPanel.vue')
    const wrapper = mount(FolderCenterPanel, { props: { nodeId: 'node-1' } })

    const row = wrapper.find('[data-testid="conv-row-conv-1"]')
    expect(row.exists()).toBe(true)
    await row.trigger('click')

    expect(wrapper.emitted('open-conversation')).toBeTruthy()
    expect(wrapper.emitted('open-conversation')![0]).toEqual(['conv-1'])
  })

  it('conversation rows are draggable with correct dataTransfer payload', async () => {
    const convs = [makeConv({ id: 'conv-99', context_node_id: 'node-1' })]
    mockUseConversationsStore.mockReturnValue(makeConvStore(convs) as any)
    mockUseContextStore.mockReturnValue(makeContextStore() as any)

    const { default: FolderCenterPanel } = await import('../FolderCenterPanel.vue')
    const wrapper = mount(FolderCenterPanel, { props: { nodeId: 'node-1' } })

    const row = wrapper.find('[data-testid="conv-row-conv-99"]')
    expect(row.exists()).toBe(true)
    expect(row.attributes('draggable')).toBe('true')

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

  it('emits open-conversation after successful create when Start chat is clicked', async () => {
    const newConv = makeConv({ id: 'new-conv-id' })
    const store = makeConvStore()
    store.create = vi.fn().mockResolvedValue(newConv)
    mockUseConversationsStore.mockReturnValue(store as any)
    mockUseContextStore.mockReturnValue(makeContextStore() as any)

    const { default: FolderCenterPanel } = await import('../FolderCenterPanel.vue')
    const wrapper = mount(FolderCenterPanel, { props: { nodeId: 'node-1' } })

    const textarea = wrapper.find('textarea')
    await textarea.setValue('New chat name')

    const btn = wrapper.find('[data-testid="start-chat-btn"]')
    await btn.trigger('click')
    await flushPromises()

    expect(store.create).toHaveBeenCalledWith({
      name: 'New chat name',
      context_node_id: 'node-1',
    })
    expect(wrapper.emitted('open-conversation')![0]).toEqual(['new-conv-id'])
  })
})
