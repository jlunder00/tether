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
    // Editing operations (K1-PR2)
    patchNode: vi.fn().mockResolvedValue({}),
    createNode: vi.fn().mockResolvedValue({ id: 'new-node', name: 'New Folder', parent_id: null }),
    deleteNode: vi.fn().mockResolvedValue(undefined),
    moveNode: vi.fn().mockResolvedValue(undefined),
  })
}

function makeConversationsStore(overrides: Record<string, any> = {}) {
  return {
    selectedId: null,
    list: [] as any[],
    assignNode: vi.fn().mockResolvedValue(undefined),
    refresh: vi.fn().mockResolvedValue(undefined),
    select: vi.fn(),
    ...overrides,
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

  it('shows expand chevron for node with children_count undefined (list fetch)', () => {
    // children_count is absent from list-fetch responses — show chevron optimistically
    const node = makeNode({ id: 'node-1', name: 'Parent' })
    delete (node as any).children_count
    mockUseContextStore.mockReturnValue(makeContextStore([node]) as any)
    mockUseConversationsStore.mockReturnValue(makeConversationsStore() as any)

    const wrapper = mount(ContextNodeSidebar, {
      props: { activeNodeId: null },
    })

    const chevron = wrapper.find('[data-testid="expand-chevron-node-1"]')
    expect(chevron.exists()).toBe(true)
  })

  it('does not show expand chevron for node with children_count === 0', () => {
    const nodes = [makeNode({ id: 'node-1', name: 'Leaf', children_count: 0 })]
    mockUseContextStore.mockReturnValue(makeContextStore(nodes) as any)
    mockUseConversationsStore.mockReturnValue(makeConversationsStore() as any)

    const wrapper = mount(ContextNodeSidebar, {
      props: { activeNodeId: null },
    })

    const chevron = wrapper.find('[data-testid="expand-chevron-node-1"]')
    expect(chevron.exists()).toBe(false)
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

    // Should have drag-over highlight class (token-themed via scoped CSS)
    expect(dropZone.classes()).toContain('drag-over')
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

  it('emits collapse when collapse button is clicked', async () => {
    mockUseContextStore.mockReturnValue(makeContextStore() as any)
    mockUseConversationsStore.mockReturnValue(makeConversationsStore() as any)

    const wrapper = mount(ContextNodeSidebar, {
      props: { activeNodeId: null },
    })

    const collapseBtn = wrapper.find('[data-testid="sidebar-collapse-btn"]')
    expect(collapseBtn.exists()).toBe(true)
    await collapseBtn.trigger('click')

    expect(wrapper.emitted('collapse')).toBeTruthy()
  })

  it('shows conversation leaves under expanded node', async () => {
    const nodes = [makeNode({ id: 'node-1', name: 'Parent', children_count: 0 })]
    const convStore = {
      assignNode: vi.fn().mockResolvedValue(undefined),
      selectedId: null,
      list: [
        {
          id: 'conv-1', name: 'Leaf Conv', context_node_id: 'node-1',
          type: 'interactive', priority: 'normal', state: 'open',
          thread_key: null, is_system: false,
          created_at: '2026-01-01T00:00:00Z',
          last_message_at: '2026-01-01T00:01:00Z',
          folder_name: 'Parent',
        },
      ],
      refresh: vi.fn().mockResolvedValue(undefined),
      select: vi.fn(),
    }
    mockUseContextStore.mockReturnValue(makeContextStore(nodes) as any)
    mockUseConversationsStore.mockReturnValue(convStore as any)

    // First mount uses nodes with children_count: 0 (no expansion possible)
    // Re-mount with a node where children_count is undefined to allow expansion
    const nodeWithConvs = makeNode({ id: 'node-1', name: 'Parent' })
    delete (nodeWithConvs as any).children_count
    mockUseContextStore.mockReturnValue(makeContextStore([nodeWithConvs]) as any)

    const wrapper2 = mount(ContextNodeSidebar, {
      props: { activeNodeId: null },
    })

    const chevron = wrapper2.find('[data-testid="expand-chevron-node-1"]')
    await chevron.trigger('click')
    await wrapper2.vm.$nextTick()

    // The conv leaf should appear after expansion (store.list is filtered by node)
    expect(wrapper2.text()).toContain('Leaf Conv')
  })

  it('shows "+ New chat" row under expanded folder', async () => {
    const nodeWithConvs = makeNode({ id: 'node-1', name: 'Parent' })
    delete (nodeWithConvs as any).children_count
    const convStore = {
      assignNode: vi.fn().mockResolvedValue(undefined),
      selectedId: null,
      list: [],
      refresh: vi.fn().mockResolvedValue(undefined),
      select: vi.fn(),
    }
    mockUseContextStore.mockReturnValue(makeContextStore([nodeWithConvs]) as any)
    mockUseConversationsStore.mockReturnValue(convStore as any)

    const wrapper = mount(ContextNodeSidebar, {
      props: { activeNodeId: null },
    })

    const chevron = wrapper.find('[data-testid="expand-chevron-node-1"]')
    await chevron.trigger('click')
    await wrapper.vm.$nextTick()

    expect(wrapper.text()).toContain('New chat')
  })

  it('clicking a conversation leaf emits open-conversation (preserves folder context)', async () => {
    const nodeWithConvs = makeNode({ id: 'node-1', name: 'Parent' })
    delete (nodeWithConvs as any).children_count
    const convStore = {
      assignNode: vi.fn().mockResolvedValue(undefined),
      selectedId: null,
      list: [
        {
          id: 'conv-click', name: 'Click Conv', context_node_id: 'node-1',
          type: 'interactive', priority: 'normal', state: 'open',
          thread_key: null, is_system: false,
          created_at: '2026-01-01T00:00:00Z',
          last_message_at: '2026-01-01T00:01:00Z',
          folder_name: 'Parent',
        },
      ],
      refresh: vi.fn().mockResolvedValue(undefined),
      select: vi.fn(),
    }
    mockUseContextStore.mockReturnValue(makeContextStore([nodeWithConvs]) as any)
    mockUseConversationsStore.mockReturnValue(convStore as any)

    const wrapper = mount(ContextNodeSidebar, {
      props: { activeNodeId: null },
    })

    const chevron = wrapper.find('[data-testid="expand-chevron-node-1"]')
    await chevron.trigger('click')
    await wrapper.vm.$nextTick()

    const leafRow = wrapper.find('[data-testid="conv-leaf-conv-click"]')
    expect(leafRow.exists()).toBe(true)
    await leafRow.trigger('click')

    // Should emit open-conversation, NOT mutate activeNodeId — parent decides
    // navigation, preserving folder context for back-navigation.
    expect(wrapper.emitted('open-conversation')).toBeTruthy()
    expect(wrapper.emitted('open-conversation')![0]).toEqual(['conv-click'])
    // Old buggy behavior was emit('update:activeNodeId', null); ensure it doesn't.
    expect(wrapper.emitted('update:activeNodeId')).toBeFalsy()
  })

  // ── K1-PR2: Inline rename ──────────────────────────────────────────────

  it('double-clicking a node name shows a rename input pre-filled with the name', async () => {
    const nodes = [makeNode({ id: 'node-1', name: 'Alpha', children_count: 0 })]
    mockUseContextStore.mockReturnValue(makeContextStore(nodes) as any)
    mockUseConversationsStore.mockReturnValue(makeConversationsStore() as any)

    const wrapper = mount(ContextNodeSidebar, { props: { activeNodeId: null } })
    const nameSpan = wrapper.find('[data-testid="node-row-node-1"]')
    await nameSpan.trigger('dblclick')

    // Input should appear in place of the span
    const input = wrapper.find('[data-testid="rename-input-node-1"]')
    expect(input.exists()).toBe(true)
    expect((input.element as HTMLInputElement).value).toBe('Alpha')
  })

  it('pressing Enter on rename input calls patchNode and hides input', async () => {
    const nodes = [makeNode({ id: 'node-1', name: 'Alpha', children_count: 0 })]
    const ctxStore = makeContextStore(nodes)
    mockUseContextStore.mockReturnValue(ctxStore as any)
    mockUseConversationsStore.mockReturnValue(makeConversationsStore() as any)

    const wrapper = mount(ContextNodeSidebar, { props: { activeNodeId: null } })
    await wrapper.find('[data-testid="node-row-node-1"]').trigger('dblclick')

    const input = wrapper.find('[data-testid="rename-input-node-1"]')
    await input.setValue('Beta')
    await input.trigger('keydown', { key: 'Enter' })
    await wrapper.vm.$nextTick()

    expect(ctxStore.patchNode).toHaveBeenCalledWith('node-1', { name: 'Beta' })
    // Input should be gone, span restored
    expect(wrapper.find('[data-testid="rename-input-node-1"]').exists()).toBe(false)
    expect(wrapper.find('[data-testid="node-row-node-1"]').exists()).toBe(true)
  })

  it('pressing Escape on rename input cancels without calling patchNode', async () => {
    const nodes = [makeNode({ id: 'node-1', name: 'Alpha', children_count: 0 })]
    const ctxStore = makeContextStore(nodes)
    mockUseContextStore.mockReturnValue(ctxStore as any)
    mockUseConversationsStore.mockReturnValue(makeConversationsStore() as any)

    const wrapper = mount(ContextNodeSidebar, { props: { activeNodeId: null } })
    await wrapper.find('[data-testid="node-row-node-1"]').trigger('dblclick')

    const input = wrapper.find('[data-testid="rename-input-node-1"]')
    await input.setValue('SomethingElse')
    await input.trigger('keydown', { key: 'Escape' })
    await wrapper.vm.$nextTick()

    expect(ctxStore.patchNode).not.toHaveBeenCalled()
    expect(wrapper.find('[data-testid="rename-input-node-1"]').exists()).toBe(false)
  })

  it('blurring the rename input commits the rename', async () => {
    const nodes = [makeNode({ id: 'node-1', name: 'Alpha', children_count: 0 })]
    const ctxStore = makeContextStore(nodes)
    mockUseContextStore.mockReturnValue(ctxStore as any)
    mockUseConversationsStore.mockReturnValue(makeConversationsStore() as any)

    const wrapper = mount(ContextNodeSidebar, { props: { activeNodeId: null } })
    await wrapper.find('[data-testid="node-row-node-1"]').trigger('dblclick')

    const input = wrapper.find('[data-testid="rename-input-node-1"]')
    await input.setValue('Gamma')
    await input.trigger('blur')
    await wrapper.vm.$nextTick()

    expect(ctxStore.patchNode).toHaveBeenCalledWith('node-1', { name: 'Gamma' })
  })

  it('rename does not call patchNode when value is unchanged', async () => {
    const nodes = [makeNode({ id: 'node-1', name: 'Alpha', children_count: 0 })]
    const ctxStore = makeContextStore(nodes)
    mockUseContextStore.mockReturnValue(ctxStore as any)
    mockUseConversationsStore.mockReturnValue(makeConversationsStore() as any)

    const wrapper = mount(ContextNodeSidebar, { props: { activeNodeId: null } })
    await wrapper.find('[data-testid="node-row-node-1"]').trigger('dblclick')

    const input = wrapper.find('[data-testid="rename-input-node-1"]')
    // Do not change value (still 'Alpha')
    await input.trigger('keydown', { key: 'Enter' })
    await wrapper.vm.$nextTick()

    expect(ctxStore.patchNode).not.toHaveBeenCalled()
  })

  it('rename does not call patchNode when value is blank after trim', async () => {
    const nodes = [makeNode({ id: 'node-1', name: 'Alpha', children_count: 0 })]
    const ctxStore = makeContextStore(nodes)
    mockUseContextStore.mockReturnValue(ctxStore as any)
    mockUseConversationsStore.mockReturnValue(makeConversationsStore() as any)

    const wrapper = mount(ContextNodeSidebar, { props: { activeNodeId: null } })
    await wrapper.find('[data-testid="node-row-node-1"]').trigger('dblclick')

    const input = wrapper.find('[data-testid="rename-input-node-1"]')
    await input.setValue('   ')
    await input.trigger('keydown', { key: 'Enter' })
    await wrapper.vm.$nextTick()

    expect(ctxStore.patchNode).not.toHaveBeenCalled()
  })

  // ── K1-PR2: Create folder ──────────────────────────────────────────────

  it('shows a "+" create button on each root folder row', () => {
    const nodes = [makeNode({ id: 'node-1', name: 'Alpha', children_count: 0 })]
    mockUseContextStore.mockReturnValue(makeContextStore(nodes) as any)
    mockUseConversationsStore.mockReturnValue(makeConversationsStore() as any)

    const wrapper = mount(ContextNodeSidebar, { props: { activeNodeId: null } })
    expect(wrapper.find('[data-testid="create-child-btn-node-1"]').exists()).toBe(true)
  })

  it('clicking the folder "+" button shows an inline create input', async () => {
    const nodes = [makeNode({ id: 'node-1', name: 'Alpha', children_count: 0 })]
    mockUseContextStore.mockReturnValue(makeContextStore(nodes) as any)
    mockUseConversationsStore.mockReturnValue(makeConversationsStore() as any)

    const wrapper = mount(ContextNodeSidebar, { props: { activeNodeId: null } })
    await wrapper.find('[data-testid="create-child-btn-node-1"]').trigger('click')

    expect(wrapper.find('[data-testid="create-input-node-1"]').exists()).toBe(true)
  })

  it('Enter on create input calls createNode with parentId and name, then hides input', async () => {
    const nodes = [makeNode({ id: 'node-1', name: 'Alpha', children_count: 0 })]
    const ctxStore = makeContextStore(nodes)
    mockUseContextStore.mockReturnValue(ctxStore as any)
    mockUseConversationsStore.mockReturnValue(makeConversationsStore() as any)

    const wrapper = mount(ContextNodeSidebar, { props: { activeNodeId: null } })
    await wrapper.find('[data-testid="create-child-btn-node-1"]').trigger('click')

    const input = wrapper.find('[data-testid="create-input-node-1"]')
    await input.setValue('Child Folder')
    await input.trigger('keydown', { key: 'Enter' })
    await wrapper.vm.$nextTick()

    expect(ctxStore.createNode).toHaveBeenCalledWith('node-1', 'Child Folder')
    expect(wrapper.find('[data-testid="create-input-node-1"]').exists()).toBe(false)
  })

  it('Escape on create input cancels without calling createNode', async () => {
    const nodes = [makeNode({ id: 'node-1', name: 'Alpha', children_count: 0 })]
    const ctxStore = makeContextStore(nodes)
    mockUseContextStore.mockReturnValue(ctxStore as any)
    mockUseConversationsStore.mockReturnValue(makeConversationsStore() as any)

    const wrapper = mount(ContextNodeSidebar, { props: { activeNodeId: null } })
    await wrapper.find('[data-testid="create-child-btn-node-1"]').trigger('click')

    await wrapper.find('[data-testid="create-input-node-1"]').trigger('keydown', { key: 'Escape' })
    await wrapper.vm.$nextTick()

    expect(ctxStore.createNode).not.toHaveBeenCalled()
    expect(wrapper.find('[data-testid="create-input-node-1"]').exists()).toBe(false)
  })

  it('shows a "New root folder" affordance', () => {
    mockUseContextStore.mockReturnValue(makeContextStore() as any)
    mockUseConversationsStore.mockReturnValue(makeConversationsStore() as any)

    const wrapper = mount(ContextNodeSidebar, { props: { activeNodeId: null } })
    expect(wrapper.find('[data-testid="create-root-btn"]').exists()).toBe(true)
  })

  it('clicking "New root folder" shows a root create input; Enter calls createNode(null, name)', async () => {
    const ctxStore = makeContextStore()
    mockUseContextStore.mockReturnValue(ctxStore as any)
    mockUseConversationsStore.mockReturnValue(makeConversationsStore() as any)

    const wrapper = mount(ContextNodeSidebar, { props: { activeNodeId: null } })
    await wrapper.find('[data-testid="create-root-btn"]').trigger('click')

    const input = wrapper.find('[data-testid="create-input-root"]')
    expect(input.exists()).toBe(true)
    await input.setValue('Root Folder')
    await input.trigger('keydown', { key: 'Enter' })
    await wrapper.vm.$nextTick()

    expect(ctxStore.createNode).toHaveBeenCalledWith(null, 'Root Folder')
    expect(wrapper.find('[data-testid="create-input-root"]').exists()).toBe(false)
  })

  it('create does not call createNode when name is blank', async () => {
    const nodes = [makeNode({ id: 'node-1', name: 'Alpha', children_count: 0 })]
    const ctxStore = makeContextStore(nodes)
    mockUseContextStore.mockReturnValue(ctxStore as any)
    mockUseConversationsStore.mockReturnValue(makeConversationsStore() as any)

    const wrapper = mount(ContextNodeSidebar, { props: { activeNodeId: null } })
    await wrapper.find('[data-testid="create-child-btn-node-1"]').trigger('click')

    const input = wrapper.find('[data-testid="create-input-node-1"]')
    await input.setValue('   ')
    await input.trigger('keydown', { key: 'Enter' })
    await wrapper.vm.$nextTick()

    expect(ctxStore.createNode).not.toHaveBeenCalled()
  })

  // ── K1-PR2: Delete folder ──────────────────────────────────────────────

  it('shows a delete button on each root folder row', () => {
    const nodes = [makeNode({ id: 'node-1', name: 'Alpha', children_count: 0 })]
    mockUseContextStore.mockReturnValue(makeContextStore(nodes) as any)
    mockUseConversationsStore.mockReturnValue(makeConversationsStore() as any)

    const wrapper = mount(ContextNodeSidebar, { props: { activeNodeId: null } })
    expect(wrapper.find('[data-testid="delete-btn-node-1"]').exists()).toBe(true)
  })

  it('clicking delete button shows confirmation dialog with node name', async () => {
    const nodes = [makeNode({ id: 'node-1', name: 'Alpha', children_count: 0 })]
    mockUseContextStore.mockReturnValue(makeContextStore(nodes) as any)
    mockUseConversationsStore.mockReturnValue(makeConversationsStore() as any)

    const wrapper = mount(ContextNodeSidebar, { props: { activeNodeId: null } })
    await wrapper.find('[data-testid="delete-btn-node-1"]').trigger('click')

    const dialog = wrapper.find('[data-testid="delete-confirm-dialog"]')
    expect(dialog.exists()).toBe(true)
    expect(dialog.text()).toContain('Alpha')
  })

  it('delete confirmation mentions subfolders count when children_count > 0', async () => {
    const nodes = [makeNode({ id: 'node-1', name: 'Alpha', children_count: 3 })]
    mockUseContextStore.mockReturnValue(makeContextStore(nodes) as any)
    mockUseConversationsStore.mockReturnValue(makeConversationsStore() as any)

    const wrapper = mount(ContextNodeSidebar, { props: { activeNodeId: null } })
    await wrapper.find('[data-testid="delete-btn-node-1"]').trigger('click')

    const dialog = wrapper.find('[data-testid="delete-confirm-dialog"]')
    expect(dialog.text()).toContain('3 subfolder')
  })

  it('delete confirmation omits subfolder sentence when children_count === 0', async () => {
    const nodes = [makeNode({ id: 'node-1', name: 'Alpha', children_count: 0 })]
    mockUseContextStore.mockReturnValue(makeContextStore(nodes) as any)
    mockUseConversationsStore.mockReturnValue(makeConversationsStore() as any)

    const wrapper = mount(ContextNodeSidebar, { props: { activeNodeId: null } })
    await wrapper.find('[data-testid="delete-btn-node-1"]').trigger('click')

    const dialog = wrapper.find('[data-testid="delete-confirm-dialog"]')
    expect(dialog.text()).not.toContain('subfolder')
  })

  it('delete confirmation mentions conversations moving to All conversations', async () => {
    const nodes = [makeNode({ id: 'node-1', name: 'Alpha', children_count: 0 })]
    mockUseContextStore.mockReturnValue(makeContextStore(nodes) as any)
    mockUseConversationsStore.mockReturnValue(makeConversationsStore() as any)

    const wrapper = mount(ContextNodeSidebar, { props: { activeNodeId: null } })
    await wrapper.find('[data-testid="delete-btn-node-1"]').trigger('click')

    const dialog = wrapper.find('[data-testid="delete-confirm-dialog"]')
    expect(dialog.text()).toContain('All conversations')
  })

  it('confirming delete calls deleteNode and closes dialog', async () => {
    const nodes = [makeNode({ id: 'node-1', name: 'Alpha', children_count: 0 })]
    const ctxStore = makeContextStore(nodes)
    mockUseContextStore.mockReturnValue(ctxStore as any)
    mockUseConversationsStore.mockReturnValue(makeConversationsStore() as any)

    const wrapper = mount(ContextNodeSidebar, { props: { activeNodeId: null } })
    await wrapper.find('[data-testid="delete-btn-node-1"]').trigger('click')
    await wrapper.find('[data-testid="delete-confirm-ok"]').trigger('click')
    await wrapper.vm.$nextTick()

    expect(ctxStore.deleteNode).toHaveBeenCalledWith('node-1')
    expect(wrapper.find('[data-testid="delete-confirm-dialog"]').exists()).toBe(false)
  })

  it('cancelling delete does not call deleteNode and closes dialog', async () => {
    const nodes = [makeNode({ id: 'node-1', name: 'Alpha', children_count: 0 })]
    const ctxStore = makeContextStore(nodes)
    mockUseContextStore.mockReturnValue(ctxStore as any)
    mockUseConversationsStore.mockReturnValue(makeConversationsStore() as any)

    const wrapper = mount(ContextNodeSidebar, { props: { activeNodeId: null } })
    await wrapper.find('[data-testid="delete-btn-node-1"]').trigger('click')
    await wrapper.find('[data-testid="delete-confirm-cancel"]').trigger('click')
    await wrapper.vm.$nextTick()

    expect(ctxStore.deleteNode).not.toHaveBeenCalled()
    expect(wrapper.find('[data-testid="delete-confirm-dialog"]').exists()).toBe(false)
  })

  // ── K1-PR2: Folder drag-and-drop reparent ─────────────────────────────

  it('folder rows are draggable', () => {
    const nodes = [makeNode({ id: 'node-1', name: 'Alpha', children_count: 0 })]
    mockUseContextStore.mockReturnValue(makeContextStore(nodes) as any)
    mockUseConversationsStore.mockReturnValue(makeConversationsStore() as any)

    const wrapper = mount(ContextNodeSidebar, { props: { activeNodeId: null } })
    const dropZone = wrapper.find('[data-testid="drop-zone-node-1"]')
    expect(dropZone.attributes('draggable')).toBe('true')
  })

  it('dragstart on a folder row sets application/x-tether-folder dataTransfer', async () => {
    const nodes = [makeNode({ id: 'node-1', name: 'Alpha', children_count: 0 })]
    mockUseContextStore.mockReturnValue(makeContextStore(nodes) as any)
    mockUseConversationsStore.mockReturnValue(makeConversationsStore() as any)

    const wrapper = mount(ContextNodeSidebar, { props: { activeNodeId: null } })
    const dropZone = wrapper.find('[data-testid="drop-zone-node-1"]')

    const setDataMock = vi.fn()
    const dragEvent = new Event('dragstart') as any
    dragEvent.dataTransfer = { setData: setDataMock, effectAllowed: '' }
    await dropZone.element.dispatchEvent(dragEvent)

    expect(setDataMock).toHaveBeenCalledWith(
      'application/x-tether-folder',
      JSON.stringify({ folderId: 'node-1' }),
    )
  })

  it('dropping a folder onto another folder calls moveNode(folderId, targetId)', async () => {
    const nodes = [
      makeNode({ id: 'node-a', name: 'Alpha', children_count: 0 }),
      makeNode({ id: 'node-b', name: 'Beta', children_count: 0 }),
    ]
    const ctxStore = makeContextStore(nodes)
    mockUseContextStore.mockReturnValue(ctxStore as any)
    mockUseConversationsStore.mockReturnValue(makeConversationsStore() as any)

    const wrapper = mount(ContextNodeSidebar, { props: { activeNodeId: null } })

    // Drop node-a onto node-b
    const dropZoneB = wrapper.find('[data-testid="drop-zone-node-b"]')
    const dropEvent = new Event('drop') as any
    dropEvent.preventDefault = vi.fn()
    dropEvent.dataTransfer = {
      getData: vi.fn().mockImplementation((type: string) => {
        if (type === 'application/x-tether-folder') return JSON.stringify({ folderId: 'node-a' })
        return ''
      }),
      types: ['application/x-tether-folder'],
    }
    await dropZoneB.element.dispatchEvent(dropEvent)
    await wrapper.vm.$nextTick()

    expect(ctxStore.moveNode).toHaveBeenCalledWith('node-a', 'node-b')
  })

  it('dropping a folder onto root zone calls moveNode(folderId, null)', async () => {
    const nodes = [makeNode({ id: 'node-1', name: 'Alpha', children_count: 0 })]
    const ctxStore = makeContextStore(nodes)
    mockUseContextStore.mockReturnValue(ctxStore as any)
    mockUseConversationsStore.mockReturnValue(makeConversationsStore() as any)

    const wrapper = mount(ContextNodeSidebar, { props: { activeNodeId: null } })

    const rootDropZone = wrapper.find('[data-testid="all-item"]')
    const dropEvent = new Event('drop') as any
    dropEvent.preventDefault = vi.fn()
    dropEvent.dataTransfer = {
      getData: vi.fn().mockImplementation((type: string) => {
        if (type === 'application/x-tether-folder') return JSON.stringify({ folderId: 'node-1' })
        return ''
      }),
      types: ['application/x-tether-folder'],
    }
    await rootDropZone.element.dispatchEvent(dropEvent)
    await wrapper.vm.$nextTick()

    expect(ctxStore.moveNode).toHaveBeenCalledWith('node-1', null)
  })

  it('dropping a folder onto itself does not call moveNode', async () => {
    const nodes = [makeNode({ id: 'node-1', name: 'Alpha', children_count: 0 })]
    const ctxStore = makeContextStore(nodes)
    mockUseContextStore.mockReturnValue(ctxStore as any)
    mockUseConversationsStore.mockReturnValue(makeConversationsStore() as any)

    const wrapper = mount(ContextNodeSidebar, { props: { activeNodeId: null } })

    const dropZone = wrapper.find('[data-testid="drop-zone-node-1"]')
    const dropEvent = new Event('drop') as any
    dropEvent.preventDefault = vi.fn()
    dropEvent.dataTransfer = {
      getData: vi.fn().mockImplementation((type: string) => {
        if (type === 'application/x-tether-folder') return JSON.stringify({ folderId: 'node-1' })
        return ''
      }),
      types: ['application/x-tether-folder'],
    }
    await dropZone.element.dispatchEvent(dropEvent)
    await wrapper.vm.$nextTick()

    expect(ctxStore.moveNode).not.toHaveBeenCalled()
  })

  it('existing conversation drag still calls assignNode (not moveNode)', async () => {
    const nodes = [makeNode({ id: 'node-1', name: 'Alpha', children_count: 0 })]
    const ctxStore = makeContextStore(nodes)
    const convStore = makeConversationsStore()
    mockUseContextStore.mockReturnValue(ctxStore as any)
    mockUseConversationsStore.mockReturnValue(convStore as any)

    const wrapper = mount(ContextNodeSidebar, { props: { activeNodeId: null } })

    const dropZone = wrapper.find('[data-testid="drop-zone-node-1"]')
    const dropEvent = new Event('drop') as any
    dropEvent.preventDefault = vi.fn()
    dropEvent.dataTransfer = {
      getData: vi.fn().mockImplementation((type: string) => {
        if (type === 'text/plain') return JSON.stringify({ conversationId: 'conv-99' })
        return ''
      }),
      types: ['text/plain'],
    }
    await dropZone.element.dispatchEvent(dropEvent)
    await wrapper.vm.$nextTick()

    expect(convStore.assignNode).toHaveBeenCalledWith('conv-99', 'node-1')
    expect(ctxStore.moveNode).not.toHaveBeenCalled()
  })

  it('conversation leaves are draggable with correct dataTransfer payload', async () => {
    const nodeWithConvs = makeNode({ id: 'node-1', name: 'Parent' })
    delete (nodeWithConvs as any).children_count
    const convStore = {
      assignNode: vi.fn().mockResolvedValue(undefined),
      selectedId: null,
      list: [
        {
          id: 'conv-drag', name: 'Draggable Conv', context_node_id: 'node-1',
          type: 'interactive', priority: 'normal', state: 'open',
          thread_key: null, is_system: false,
          created_at: '2026-01-01T00:00:00Z',
          last_message_at: '2026-01-01T00:01:00Z',
          folder_name: 'Parent',
        },
      ],
      refresh: vi.fn().mockResolvedValue(undefined),
      select: vi.fn(),
    }
    mockUseContextStore.mockReturnValue(makeContextStore([nodeWithConvs]) as any)
    mockUseConversationsStore.mockReturnValue(convStore as any)

    const wrapper = mount(ContextNodeSidebar, {
      props: { activeNodeId: null },
    })

    const chevron = wrapper.find('[data-testid="expand-chevron-node-1"]')
    await chevron.trigger('click')
    await wrapper.vm.$nextTick()

    const leafRow = wrapper.find('[data-testid="conv-leaf-conv-drag"]')
    expect(leafRow.exists()).toBe(true)
    expect(leafRow.attributes('draggable')).toBe('true')

    const setDataMock = vi.fn()
    const dragEvent = new Event('dragstart') as any
    dragEvent.dataTransfer = { setData: setDataMock }
    await leafRow.element.dispatchEvent(dragEvent)
    await wrapper.vm.$nextTick()

    expect(setDataMock).toHaveBeenCalledWith(
      'text/plain',
      JSON.stringify({ conversationId: 'conv-drag' })
    )
  })
})
