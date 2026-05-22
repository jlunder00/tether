import { describe, it, expect, vi, beforeEach } from 'vitest'
import { mount } from '@vue/test-utils'
import { setActivePinia, createPinia } from 'pinia'
import { computed, reactive } from 'vue'

// Mock both stores
vi.mock('../../../stores/context', () => ({
  useContextStore: vi.fn(),
}))
vi.mock('../../../stores/conversations', () => ({
  useConversationsStore: vi.fn(),
}))

import { useContextStore } from '../../../stores/context'
import { useConversationsStore } from '../../../stores/conversations'
import ContextNodeSidebar from '../ContextNodeSidebar.vue'

const mockUseContextStore = vi.mocked(useContextStore)
const mockUseConversationsStore = vi.mocked(useConversationsStore)

function makeNode(overrides = {}) {
  return {
    id: 'node-1',
    parent_id: null,
    name: 'Test Node',
    description: null,
    node_type: 'context' as const,
    archived: false,
    target_date: null,
    status: null,
    status_override: false,
    color: null,
    created_at: '2026-01-01T00:00:00Z',
    updated_at: '2026-01-01T00:00:00Z',
    children_count: 0,
    ...overrides,
  }
}

function makeContextStore(nodes: ReturnType<typeof makeNode>[] = []) {
  // Use reactive so that computed refs are auto-unwrapped (mirroring Pinia store behavior)
  return reactive({
    nodes: {} as Record<string, ReturnType<typeof makeNode>>,
    rootNodes: computed(() => nodes),
    fetchRootNodes: vi.fn().mockResolvedValue(nodes),
    fetchChildren: vi.fn().mockResolvedValue([]),
    childrenOf: vi.fn().mockReturnValue([]),
  })
}

function makeConversationsStore() {
  return {
    assignNode: vi.fn().mockResolvedValue(undefined),
  }
}

describe('ContextNodeSidebar', () => {
  beforeEach(() => {
    setActivePinia(createPinia())
    vi.clearAllMocks()
  })

  it('mounts without error', () => {
    mockUseContextStore.mockReturnValue(makeContextStore() as any)
    mockUseConversationsStore.mockReturnValue(makeConversationsStore() as any)

    const wrapper = mount(ContextNodeSidebar, {
      props: { activeNodeId: null },
    })
    expect(wrapper.exists()).toBe(true)
  })

  it('shows "All conversations" option at top', () => {
    mockUseContextStore.mockReturnValue(makeContextStore() as any)
    mockUseConversationsStore.mockReturnValue(makeConversationsStore() as any)

    const wrapper = mount(ContextNodeSidebar, {
      props: { activeNodeId: null },
    })
    expect(wrapper.text()).toContain('All')
  })

  it('clicking "All" emits update:activeNodeId with null', async () => {
    mockUseContextStore.mockReturnValue(makeContextStore() as any)
    mockUseConversationsStore.mockReturnValue(makeConversationsStore() as any)

    const wrapper = mount(ContextNodeSidebar, {
      props: { activeNodeId: 'node-1' },
    })

    const allItem = wrapper.find('[data-testid="all-item"]')
    await allItem.trigger('click')

    expect(wrapper.emitted('update:activeNodeId')).toBeTruthy()
    expect(wrapper.emitted('update:activeNodeId')![0]).toEqual([null])
  })

  it('shows root nodes from contextStore.rootNodes', () => {
    const nodes = [
      makeNode({ id: 'node-1', name: 'Alpha' }),
      makeNode({ id: 'node-2', name: 'Beta' }),
    ]
    mockUseContextStore.mockReturnValue(makeContextStore(nodes) as any)
    mockUseConversationsStore.mockReturnValue(makeConversationsStore() as any)

    const wrapper = mount(ContextNodeSidebar, {
      props: { activeNodeId: null },
    })
    expect(wrapper.text()).toContain('Alpha')
    expect(wrapper.text()).toContain('Beta')
  })

  it('clicking a node row emits update:activeNodeId with the node id', async () => {
    const nodes = [makeNode({ id: 'node-1', name: 'Alpha' })]
    mockUseContextStore.mockReturnValue(makeContextStore(nodes) as any)
    mockUseConversationsStore.mockReturnValue(makeConversationsStore() as any)

    const wrapper = mount(ContextNodeSidebar, {
      props: { activeNodeId: null },
    })

    const nodeRow = wrapper.find('[data-testid="node-row-node-1"]')
    await nodeRow.trigger('click')

    expect(wrapper.emitted('update:activeNodeId')).toBeTruthy()
    expect(wrapper.emitted('update:activeNodeId')![0]).toEqual(['node-1'])
  })

  it('shows expand chevron for node with children_count > 0', () => {
    const nodes = [makeNode({ id: 'node-1', name: 'Parent', children_count: 3 })]
    mockUseContextStore.mockReturnValue(makeContextStore(nodes) as any)
    mockUseConversationsStore.mockReturnValue(makeConversationsStore() as any)

    const wrapper = mount(ContextNodeSidebar, {
      props: { activeNodeId: null },
    })

    const chevron = wrapper.find('[data-testid="expand-chevron-node-1"]')
    expect(chevron.exists()).toBe(true)
  })

  it('clicking expand chevron calls contextStore.fetchChildren(nodeId)', async () => {
    const contextStore = makeContextStore([
      makeNode({ id: 'node-1', name: 'Parent', children_count: 2 }),
    ])
    mockUseContextStore.mockReturnValue(contextStore as any)
    mockUseConversationsStore.mockReturnValue(makeConversationsStore() as any)

    const wrapper = mount(ContextNodeSidebar, {
      props: { activeNodeId: null },
    })

    const chevron = wrapper.find('[data-testid="expand-chevron-node-1"]')
    await chevron.trigger('click')

    expect(contextStore.fetchChildren).toHaveBeenCalledWith('node-1')
  })

  it('shows drag-over highlight when dragover event fires on a node row', async () => {
    const nodes = [makeNode({ id: 'node-1', name: 'Alpha' })]
    mockUseContextStore.mockReturnValue(makeContextStore(nodes) as any)
    mockUseConversationsStore.mockReturnValue(makeConversationsStore() as any)

    const wrapper = mount(ContextNodeSidebar, {
      props: { activeNodeId: null },
    })

    const dropZone = wrapper.find('[data-testid="drop-zone-node-1"]')
    await dropZone.trigger('dragover')

    // Should have drag-over highlight class
    expect(dropZone.classes()).toContain('ring-2')
  })

  it('calls conversationsStore.assignNode on drop with conversation id', async () => {
    const nodes = [makeNode({ id: 'node-1', name: 'Alpha' })]
    const conversationsStore = makeConversationsStore()
    mockUseContextStore.mockReturnValue(makeContextStore(nodes) as any)
    mockUseConversationsStore.mockReturnValue(conversationsStore as any)

    const wrapper = mount(ContextNodeSidebar, {
      props: { activeNodeId: null },
    })

    const dropZone = wrapper.find('[data-testid="drop-zone-node-1"]')

    // Simulate drop with dataTransfer
    const dropEvent = new Event('drop') as any
    dropEvent.preventDefault = vi.fn()
    dropEvent.dataTransfer = {
      getData: vi.fn().mockReturnValue(JSON.stringify({ conversationId: 'conv-123' })),
    }
    await dropZone.element.dispatchEvent(dropEvent)
    await wrapper.vm.$nextTick()

    expect(conversationsStore.assignNode).toHaveBeenCalledWith('conv-123', 'node-1')
  })
})
