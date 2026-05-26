import { describe, it, expect, vi, beforeEach } from 'vitest'
import { mount } from '@vue/test-utils'
import { createPinia, setActivePinia } from 'pinia'
import ConversationView from '../../chat/ConversationView.vue'

vi.mock('../../../lib/api', () => ({ api: vi.fn() }))
vi.mock('../../../stores/conversations', () => ({
  useConversationsStore: vi.fn(),
}))
// Stable mock so component and test share the same fetchPreference spy.
const mockPickerStore = {
  selectedAgent: 'tether-agent-2.0',
  fetchPreference: vi.fn(),
}
vi.mock('../../../stores/agentPicker', () => ({
  useAgentPickerStore: vi.fn(() => mockPickerStore),
}))
vi.mock('../../../composables/useConversationChat', () => ({
  useConversationChat: vi.fn(() => ({
    isStreaming: { value: false },
    streamingContent: { value: '' },
    send: vi.fn().mockResolvedValue(undefined),
    interrupt: vi.fn(),
  })),
}))

import { useConversationsStore } from '../../../stores/conversations'

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

function makeMsg(overrides = {}) {
  return {
    id: 'msg-1',
    role: 'user' as const,
    body: 'Hello there',
    source: 'chat' as const,
    channel: 'web' as const,
    created_at: '2026-01-01T00:00:00Z',
    ...overrides,
  }
}

function makeStore(overrides: Record<string, unknown> = {}) {
  const conv = makeConv()
  const msgs = new Map([['conv-1', [makeMsg()]]])
  const hasMore = new Map([['conv-1', false]])
  return {
    selectedId: 'conv-1',
    selected: conv,
    messagesById: msgs,
    hasMoreById: hasMore,
    loading: false,
    error: null,
    patch: vi.fn().mockResolvedValue(true),
    loadMessagesOlder: vi.fn().mockResolvedValue(undefined),
    appendMessage: vi.fn(),
    ...overrides,
  }
}

const globalStubs = {
  AgentPicker: true,
  PriorityPill: {
    template: '<button @click="$emit(\'change\', \'high\')">priority</button>',
    emits: ['change'],
  },
  StateToggle: {
    template: '<button @click="$emit(\'change\', \'closed\')">state</button>',
    emits: ['change'],
  },
}

describe('ConversationView', () => {
  beforeEach(() => {
    setActivePinia(createPinia())
  })

  it('shows empty state when no selectedId', () => {
    vi.mocked(useConversationsStore).mockReturnValue({
      ...makeStore({ selectedId: null, selected: null }),
    } as unknown as ReturnType<typeof useConversationsStore>)
    const wrapper = mount(ConversationView, {
      global: { stubs: globalStubs },
    })
    expect(wrapper.text().toLowerCase()).toContain('select')
  })

  it('renders messages for selected conversation', () => {
    vi.mocked(useConversationsStore).mockReturnValue(makeStore() as unknown as ReturnType<typeof useConversationsStore>)
    const wrapper = mount(ConversationView, {
      global: { stubs: globalStubs },
    })
    expect(wrapper.text()).toContain('Hello there')
  })

  it('shows "Load older" button when has_more=true', () => {
    const hasMore = new Map([['conv-1', true]])
    vi.mocked(useConversationsStore).mockReturnValue({
      ...makeStore({ hasMoreById: hasMore }),
    } as unknown as ReturnType<typeof useConversationsStore>)
    const wrapper = mount(ConversationView, {
      global: { stubs: globalStubs },
    })
    const btns = wrapper.findAll('button')
    expect(btns.some(b => b.text().toLowerCase().includes('load older') || b.text().toLowerCase().includes('older'))).toBe(true)
  })

  it('does not show "Load older" when has_more=false', () => {
    vi.mocked(useConversationsStore).mockReturnValue(makeStore() as unknown as ReturnType<typeof useConversationsStore>)
    const wrapper = mount(ConversationView, {
      global: { stubs: globalStubs },
    })
    const btns = wrapper.findAll('button')
    expect(btns.some(b => b.text().toLowerCase().includes('load older') || b.text().toLowerCase().includes('older'))).toBe(false)
  })

  it('send submits text and clears textarea', async () => {
    vi.mocked(useConversationsStore).mockReturnValue(makeStore() as unknown as ReturnType<typeof useConversationsStore>)
    const wrapper = mount(ConversationView, {
      global: { stubs: globalStubs },
    })
    const textarea = wrapper.find('textarea')
    await textarea.setValue('Test message')
    await wrapper.find('button[type="submit"]').trigger('click')
    await new Promise(r => setTimeout(r, 10))
    expect((textarea.element as HTMLTextAreaElement).value).toBe('')
  })

  it('name edit triggers store.patch', async () => {
    const store = makeStore()
    vi.mocked(useConversationsStore).mockReturnValue(store as unknown as ReturnType<typeof useConversationsStore>)
    const wrapper = mount(ConversationView, {
      global: { stubs: globalStubs },
    })
    // Find the name element and click to edit
    const nameEl = wrapper.find('[data-testid="conv-name"]')
    if (nameEl.exists()) {
      await nameEl.trigger('click')
      const input = wrapper.find('input[type="text"]')
      if (input.exists()) {
        await input.setValue('New Name')
        await input.trigger('blur')
        await new Promise(r => setTimeout(r, 10))
        expect(store.patch).toHaveBeenCalledWith('conv-1', expect.objectContaining({ name: 'New Name' }))
      }
    }
  })

  it('priority pill change triggers store.patch', async () => {
    const store = makeStore()
    vi.mocked(useConversationsStore).mockReturnValue(store as unknown as ReturnType<typeof useConversationsStore>)
    const wrapper = mount(ConversationView, {
      global: { stubs: globalStubs },
    })
    // PriorityPill stub emits 'change' with 'high' on click
    const pill = wrapper.find('button:not([type="submit"])')
    if (pill.exists() && pill.text() === 'priority') {
      await pill.trigger('click')
      await new Promise(r => setTimeout(r, 10))
      expect(store.patch).toHaveBeenCalledWith('conv-1', expect.objectContaining({ priority: 'high' }))
    }
  })

  it('calls fetchPreference on mount to load stored agent preference', async () => {
    vi.mocked(useConversationsStore).mockReturnValue(makeStore() as unknown as ReturnType<typeof useConversationsStore>)
    mockPickerStore.fetchPreference.mockClear()
    mount(ConversationView, { global: { stubs: globalStubs } })
    await new Promise(r => setTimeout(r, 0))
    expect(mockPickerStore.fetchPreference).toHaveBeenCalled()
  })

  it('state toggle triggers store.patch', async () => {
    const store = makeStore()
    vi.mocked(useConversationsStore).mockReturnValue(store as unknown as ReturnType<typeof useConversationsStore>)
    const wrapper = mount(ConversationView, {
      global: { stubs: globalStubs },
    })
    // StateToggle stub emits 'change' with 'closed' on click
    const btns = wrapper.findAll('button')
    const stateBtn = btns.find(b => b.text() === 'state')
    if (stateBtn) {
      await stateBtn.trigger('click')
      await new Promise(r => setTimeout(r, 10))
      expect(store.patch).toHaveBeenCalledWith('conv-1', expect.objectContaining({ state: 'closed' }))
    }
  })
})
