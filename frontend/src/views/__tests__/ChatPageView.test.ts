import { describe, it, expect, vi, beforeEach } from 'vitest'
import { mount, flushPromises } from '@vue/test-utils'
import { setActivePinia, createPinia } from 'pinia'
import { reactive, ref } from 'vue'

// Mock vue-router
vi.mock('vue-router', () => ({
  useRouter: () => ({ replace: vi.fn() }),
  useRoute: () => ({ name: 'chat', params: {} }),
}))

// Mock stores
vi.mock('../../stores/conversations', () => ({
  useConversationsStore: vi.fn(),
}))
vi.mock('../../stores/context', () => ({
  useContextStore: vi.fn(),
}))

// Stub heavy child components
vi.mock('../../components/chat/ContextNodeSidebar.vue', () => ({
  default: {
    template: '<div data-testid="sidebar-stub" />',
    props: ['activeNodeId'],
    emits: ['update:activeNodeId', 'collapse'],
  },
}))
vi.mock('../../components/chat/FolderCenterPanel.vue', () => ({
  default: {
    template: '<div data-testid="folder-panel-stub" />',
    props: ['nodeId'],
    emits: ['open-conversation'],
  },
}))
vi.mock('../../components/chat/ConversationView.vue', () => ({
  default: { template: '<div data-testid="conversation-view-stub" />' },
}))
vi.mock('../../components/chat/ProjectDetailsPanel.vue', () => ({
  default: {
    template: '<div data-testid="project-details-stub" />',
    props: ['nodeId'],
    emits: ['collapse'],
  },
}))

import { useConversationsStore } from '../../stores/conversations'
import { useContextStore } from '../../stores/context'
const mockUseConversationsStore = vi.mocked(useConversationsStore)
const mockUseContextStore = vi.mocked(useContextStore)

function makeConvStore(selectedId: string | null = null) {
  return reactive({
    selectedId: ref<string | null>(selectedId),
    list: [] as any[],
    refresh: vi.fn().mockResolvedValue(undefined),
    select: vi.fn((id: string | null) => { convStoreInstance.selectedId = id }),
    fetchOne: vi.fn().mockResolvedValue(null),
  })
}
let convStoreInstance: ReturnType<typeof makeConvStore>

function makeCtxStore() {
  return reactive({
    nodes: {},
    fetchRootNodes: vi.fn().mockResolvedValue([]),
  })
}

describe('ChatPageView', () => {
  beforeEach(() => {
    setActivePinia(createPinia())
    vi.clearAllMocks()
    convStoreInstance = makeConvStore()
    mockUseConversationsStore.mockReturnValue(convStoreInstance as any)
    mockUseContextStore.mockReturnValue(makeCtxStore() as any)
  })

  it('mounts without error', async () => {
    const { default: ChatPageView } = await import('../ChatPageView.vue')
    const wrapper = mount(ChatPageView)
    expect(wrapper.exists()).toBe(true)
  })

  it('shows folder mode (FolderCenterPanel) when no conversation is selected', async () => {
    const { default: ChatPageView } = await import('../ChatPageView.vue')
    const wrapper = mount(ChatPageView)
    await flushPromises()

    expect(wrapper.find('[data-testid="folder-panel-stub"]').exists()).toBe(true)
    expect(wrapper.find('[data-testid="conversation-view-stub"]').exists()).toBe(false)
  })

  it('shows conversation mode (ConversationView) when a conversation is selected', async () => {
    convStoreInstance = makeConvStore('conv-1')
    mockUseConversationsStore.mockReturnValue(convStoreInstance as any)

    const { default: ChatPageView } = await import('../ChatPageView.vue')
    const wrapper = mount(ChatPageView)
    await flushPromises()

    expect(wrapper.find('[data-testid="conversation-view-stub"]').exists()).toBe(true)
    expect(wrapper.find('[data-testid="folder-panel-stub"]').exists()).toBe(false)
  })

  it('shows ProjectDetailsPanel in folder mode', async () => {
    const { default: ChatPageView } = await import('../ChatPageView.vue')
    const wrapper = mount(ChatPageView)
    await flushPromises()

    expect(wrapper.find('[data-testid="project-details-stub"]').exists()).toBe(true)
  })

  it('sidebar collapse hides sidebar and shows strip', async () => {
    const { default: ChatPageView } = await import('../ChatPageView.vue')
    const wrapper = mount(ChatPageView)
    await flushPromises()

    // Sidebar initially visible
    expect(wrapper.find('[data-testid="sidebar-stub"]').exists()).toBe(true)

    // Emit collapse from sidebar via vm
    const vm = wrapper.vm as any
    vm.leftOpen = false
    await wrapper.vm.$nextTick()

    // Sidebar gone, strip shown
    expect(wrapper.find('[data-testid="sidebar-stub"]').exists()).toBe(false)
    expect(wrapper.find('.k1-col-strip--left').exists()).toBe(true)
  })

  it('clicking expand strip button re-shows sidebar', async () => {
    const { default: ChatPageView } = await import('../ChatPageView.vue')
    const wrapper = mount(ChatPageView)
    await flushPromises()

    // Collapse via vm
    const vm = wrapper.vm as any
    vm.leftOpen = false
    await wrapper.vm.$nextTick()

    // Click expand button in strip
    const expandBtn = wrapper.find('.k1-col-strip--left button')
    await expandBtn.trigger('click')
    await flushPromises()

    expect(wrapper.find('[data-testid="sidebar-stub"]').exists()).toBe(true)
  })

  it('right panel collapse hides ProjectDetailsPanel and shows strip', async () => {
    const { default: ChatPageView } = await import('../ChatPageView.vue')
    const wrapper = mount(ChatPageView)
    await flushPromises()

    expect(wrapper.find('[data-testid="project-details-stub"]').exists()).toBe(true)

    // Collapse right panel via vm
    const vm = wrapper.vm as any
    vm.rightOpen = false
    await wrapper.vm.$nextTick()

    expect(wrapper.find('[data-testid="project-details-stub"]').exists()).toBe(false)
    expect(wrapper.find('.k1-col-strip--right').exists()).toBe(true)
  })
})
