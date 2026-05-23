/**
 * @handle mention autocomplete tests for ConversationView.
 *
 * Tests the @ parser and autocomplete UX in the chat composer.
 * ConversationView uses useConnectionsStore (accepted connections) for handle suggestions.
 */
import { describe, it, expect, vi, beforeEach } from 'vitest'
import { mount, flushPromises } from '@vue/test-utils'
import { createPinia, setActivePinia } from 'pinia'

vi.mock('../../../lib/api', () => ({ api: vi.fn() }))
vi.mock('../../../stores/conversations', () => ({ useConversationsStore: vi.fn() }))
vi.mock('../../../stores/agentPicker', () => ({ useAgentPickerStore: vi.fn() }))
vi.mock('../../../stores/connections', () => ({ useConnectionsStore: vi.fn() }))
vi.mock('../../../composables/useConversationChat', () => ({
  useConversationChat: vi.fn(() => ({
    send: vi.fn().mockResolvedValue(undefined),
    interrupt: vi.fn(),
    isStreaming: { value: false },
  })),
}))

import { useConversationsStore } from '../../../stores/conversations'
import { useAgentPickerStore } from '../../../stores/agentPicker'
import { useConnectionsStore } from '../../../stores/connections'

function makeConnection(username: string, overrides = {}) {
  return {
    id: Math.random(),
    user_a: 'u-a',
    user_b: 'u-b',
    status: 'accepted' as const,
    initiated_by: 'u-a',
    auto_schedule: false,
    created_at: '2026-01-01T00:00:00Z',
    updated_at: '2026-01-01T00:00:00Z',
    other_user_id: 'u-other',
    other_username: username,
    ...overrides,
  }
}

function makeConvStore(overrides = {}) {
  return {
    selectedId: 'conv-1',
    selected: { id: 'conv-1', name: 'Test', priority: 'normal', state: 'open', folder_name: null },
    messagesById: new Map([['conv-1', []]]),
    hasMoreById: new Map([['conv-1', false]]),
    appendMessage: vi.fn(),
    loadMessagesOlder: vi.fn(),
    patch: vi.fn(),
    ...overrides,
  }
}

function makeConnectionsStore(accepted: ReturnType<typeof makeConnection>[] = []) {
  return {
    accepted,
    connections: accepted,
    loading: false,
    error: null,
    fetchConnections: vi.fn().mockResolvedValue(undefined),
    ...{}
  }
}

describe('ConversationView — @handle mention autocomplete', () => {
  beforeEach(() => {
    setActivePinia(createPinia())
    vi.clearAllMocks()

    vi.mocked(useAgentPickerStore).mockReturnValue({
      fetchPreference: vi.fn(),
      agentId: null,
      loading: false,
      setAgent: vi.fn(),
    } as unknown as ReturnType<typeof useAgentPickerStore>)
  })

  it('typing "@" alone opens the autocomplete dropdown', async () => {
    vi.mocked(useConversationsStore).mockReturnValue(makeConvStore() as unknown as ReturnType<typeof useConversationsStore>)
    vi.mocked(useConnectionsStore).mockReturnValue(makeConnectionsStore([makeConnection('alice')]) as unknown as ReturnType<typeof useConnectionsStore>)

    const { default: ConversationView } = await import('../../chat/ConversationView.vue')
    const wrapper = mount(ConversationView, {
      global: { stubs: { AgentPicker: true } },
    })

    const textarea = wrapper.find('textarea')
    expect(textarea.exists()).toBe(true)

    await textarea.setValue('@')
    await textarea.trigger('input')
    await wrapper.vm.$nextTick()

    const dropdown = wrapper.find('[data-mention-dropdown]')
    expect(dropdown.exists()).toBe(true)
  })

  it('filters suggestions by typed prefix', async () => {
    vi.mocked(useConversationsStore).mockReturnValue(makeConvStore() as unknown as ReturnType<typeof useConversationsStore>)
    vi.mocked(useConnectionsStore).mockReturnValue(
      makeConnectionsStore([makeConnection('alice'), makeConnection('bob'), makeConnection('alfred')]) as unknown as ReturnType<typeof useConnectionsStore>
    )

    const { default: ConversationView } = await import('../../chat/ConversationView.vue')
    const wrapper = mount(ConversationView, {
      global: { stubs: { AgentPicker: true } },
    })

    await wrapper.find('textarea').setValue('@al')
    await wrapper.find('textarea').trigger('input')
    await wrapper.vm.$nextTick()

    const items = wrapper.findAll('[data-mention-item]')
    expect(items.length).toBe(2)
    const names = items.map(i => i.text())
    expect(names).toContain('alice')
    expect(names).toContain('alfred')
    expect(names).not.toContain('bob')
  })

  it('does NOT trigger on email address (no @ after a word char)', async () => {
    vi.mocked(useConversationsStore).mockReturnValue(makeConvStore() as unknown as ReturnType<typeof useConversationsStore>)
    vi.mocked(useConnectionsStore).mockReturnValue(
      makeConnectionsStore([makeConnection('alice')]) as unknown as ReturnType<typeof useConnectionsStore>
    )

    const { default: ConversationView } = await import('../../chat/ConversationView.vue')
    const wrapper = mount(ConversationView, {
      global: { stubs: { AgentPicker: true } },
    })

    // "name@domain" — @ preceded by a word character 'e'
    await wrapper.find('textarea').setValue('name@domain')
    await wrapper.find('textarea').trigger('input')
    await wrapper.vm.$nextTick()

    const dropdown = wrapper.find('[data-mention-dropdown]')
    expect(dropdown.exists()).toBe(false)
  })

  it('clicking a suggestion inserts @handle into the textarea', async () => {
    vi.mocked(useConversationsStore).mockReturnValue(makeConvStore() as unknown as ReturnType<typeof useConversationsStore>)
    vi.mocked(useConnectionsStore).mockReturnValue(
      makeConnectionsStore([makeConnection('alice')]) as unknown as ReturnType<typeof useConnectionsStore>
    )

    const { default: ConversationView } = await import('../../chat/ConversationView.vue')
    const wrapper = mount(ConversationView, {
      global: { stubs: { AgentPicker: true } },
    })

    await wrapper.find('textarea').setValue('@ali')
    await wrapper.find('textarea').trigger('input')
    await wrapper.vm.$nextTick()

    const item = wrapper.find('[data-mention-item]')
    expect(item.exists()).toBe(true)
    await item.trigger('click')
    await wrapper.vm.$nextTick()

    const textarea = wrapper.find('textarea')
    expect((textarea.element as HTMLTextAreaElement).value).toContain('@alice')
  })

  it('shows no more than 8 suggestions', async () => {
    const manyUsers = Array.from({ length: 12 }, (_, i) => makeConnection(`user${i}`))
    vi.mocked(useConversationsStore).mockReturnValue(makeConvStore() as unknown as ReturnType<typeof useConversationsStore>)
    vi.mocked(useConnectionsStore).mockReturnValue(
      makeConnectionsStore(manyUsers) as unknown as ReturnType<typeof useConnectionsStore>
    )

    const { default: ConversationView } = await import('../../chat/ConversationView.vue')
    const wrapper = mount(ConversationView, {
      global: { stubs: { AgentPicker: true } },
    })

    await wrapper.find('textarea').setValue('@user')
    await wrapper.find('textarea').trigger('input')
    await wrapper.vm.$nextTick()

    const items = wrapper.findAll('[data-mention-item]')
    expect(items.length).toBeLessThanOrEqual(8)
  })

  it('dropdown closes when @ trigger is deleted', async () => {
    vi.mocked(useConversationsStore).mockReturnValue(makeConvStore() as unknown as ReturnType<typeof useConversationsStore>)
    vi.mocked(useConnectionsStore).mockReturnValue(
      makeConnectionsStore([makeConnection('alice')]) as unknown as ReturnType<typeof useConnectionsStore>
    )

    const { default: ConversationView } = await import('../../chat/ConversationView.vue')
    const wrapper = mount(ConversationView, {
      global: { stubs: { AgentPicker: true } },
    })

    await wrapper.find('textarea').setValue('@ali')
    await wrapper.find('textarea').trigger('input')
    await wrapper.vm.$nextTick()
    expect(wrapper.find('[data-mention-dropdown]').exists()).toBe(true)

    // Erase back to empty
    await wrapper.find('textarea').setValue('')
    await wrapper.find('textarea').trigger('input')
    await wrapper.vm.$nextTick()
    expect(wrapper.find('[data-mention-dropdown]').exists()).toBe(false)
  })
})
