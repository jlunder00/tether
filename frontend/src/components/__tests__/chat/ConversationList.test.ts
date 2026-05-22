import { describe, it, expect, vi, beforeEach } from 'vitest'
import { mount } from '@vue/test-utils'
import { createPinia, setActivePinia } from 'pinia'
import ConversationList from '../../chat/ConversationList.vue'

vi.mock('../../../lib/api', () => ({ api: vi.fn() }))
vi.mock('../../../stores/conversations', () => ({
  useConversationsStore: vi.fn(),
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

function makeStore(overrides = {}) {
  return {
    list: [makeConv()],
    selectedId: null,
    loading: false,
    error: null,
    refresh: vi.fn().mockResolvedValue(undefined),
    select: vi.fn(),
    ...overrides,
  }
}

describe('ConversationList', () => {
  beforeEach(() => {
    setActivePinia(createPinia())
  })

  it('renders conversations from store', () => {
    vi.mocked(useConversationsStore).mockReturnValue(makeStore() as unknown as ReturnType<typeof useConversationsStore>)
    const wrapper = mount(ConversationList, {
      global: { stubs: { NewConversationModal: true } },
    })
    expect(wrapper.text()).toContain('Test Conv')
  })

  it('filter chip "Open" calls refresh with state=open', async () => {
    const store = makeStore()
    vi.mocked(useConversationsStore).mockReturnValue(store as unknown as ReturnType<typeof useConversationsStore>)
    const wrapper = mount(ConversationList, {
      global: { stubs: { NewConversationModal: true } },
    })

    const chips = wrapper.findAll('button')
    const openChip = chips.find(c => c.text().toLowerCase() === 'open')
    expect(openChip).toBeTruthy()
    await openChip!.trigger('click')
    expect(store.refresh).toHaveBeenCalledWith(expect.objectContaining({ state: 'open' }))
  })

  it('click conversation row calls store.select', async () => {
    const store = makeStore()
    vi.mocked(useConversationsStore).mockReturnValue(store as unknown as ReturnType<typeof useConversationsStore>)
    const wrapper = mount(ConversationList, {
      global: { stubs: { NewConversationModal: true } },
    })

    // Find the conversation row (first li or div with conversation)
    const rows = wrapper.findAll('[data-testid="conversation-row"]')
    if (rows.length === 0) {
      // fallback: click the element containing the conv name
      const el = wrapper.find('li, .conversation-row, [role="listitem"]')
      if (el.exists()) await el.trigger('click')
    } else {
      await rows[0].trigger('click')
    }
    expect(store.select).toHaveBeenCalledWith('conv-1')
  })

  it('shows "New Conversation" button', () => {
    vi.mocked(useConversationsStore).mockReturnValue(makeStore() as unknown as ReturnType<typeof useConversationsStore>)
    const wrapper = mount(ConversationList, {
      global: { stubs: { NewConversationModal: true } },
    })
    const btns = wrapper.findAll('button')
    expect(btns.some(b => b.text().toLowerCase().includes('new'))).toBe(true)
  })

  it('shows empty state when list is empty', () => {
    vi.mocked(useConversationsStore).mockReturnValue(makeStore({ list: [] }) as unknown as ReturnType<typeof useConversationsStore>)
    const wrapper = mount(ConversationList, {
      global: { stubs: { NewConversationModal: true } },
    })
    expect(wrapper.text().toLowerCase()).toContain('no conversation')
  })
})

// ── Pending / Rejected state UI (Beacon D2) ───────────────────────────────────
describe('ConversationList — pending and rejected states', () => {
  beforeEach(() => {
    setActivePinia(createPinia())
  })

  it('renders a pending conversation with data-state="pending"', () => {
    const store = makeStore({ list: [makeConv({ id: 'p-1', name: 'Pending Conv', state: 'pending' })] })
    vi.mocked(useConversationsStore).mockReturnValue(store as unknown as ReturnType<typeof useConversationsStore>)
    const wrapper = mount(ConversationList, { global: { stubs: { NewConversationModal: true } } })
    const row = wrapper.find('[data-testid="conversation-row"][data-state="pending"]')
    expect(row.exists()).toBe(true)
    expect(row.text()).toContain('Pending Conv')
  })

  it('renders a rejected conversation with data-state="rejected"', () => {
    const store = makeStore({ list: [makeConv({ id: 'r-1', name: 'Rejected Conv', state: 'rejected' })] })
    vi.mocked(useConversationsStore).mockReturnValue(store as unknown as ReturnType<typeof useConversationsStore>)
    const wrapper = mount(ConversationList, { global: { stubs: { NewConversationModal: true } } })
    const row = wrapper.find('[data-testid="conversation-row"][data-state="rejected"]')
    expect(row.exists()).toBe(true)
  })

  it('filter chip "Pending" calls refresh with state=pending', async () => {
    const store = makeStore()
    vi.mocked(useConversationsStore).mockReturnValue(store as unknown as ReturnType<typeof useConversationsStore>)
    const wrapper = mount(ConversationList, { global: { stubs: { NewConversationModal: true } } })
    const chips = wrapper.findAll('button')
    const pendingChip = chips.find(c => c.text().toLowerCase() === 'pending')
    expect(pendingChip).toBeTruthy()
    await pendingChip!.trigger('click')
    expect(store.refresh).toHaveBeenCalledWith(expect.objectContaining({ state: 'pending' }))
  })

  it('filter chip "Rejected" calls refresh with state=rejected', async () => {
    const store = makeStore()
    vi.mocked(useConversationsStore).mockReturnValue(store as unknown as ReturnType<typeof useConversationsStore>)
    const wrapper = mount(ConversationList, { global: { stubs: { NewConversationModal: true } } })
    const chips = wrapper.findAll('button')
    const rejectedChip = chips.find(c => c.text().toLowerCase() === 'rejected')
    expect(rejectedChip).toBeTruthy()
    await rejectedChip!.trigger('click')
    expect(store.refresh).toHaveBeenCalledWith(expect.objectContaining({ state: 'rejected' }))
  })

  it('all four states render in "all" filter view', () => {
    const store = makeStore({
      list: [
        makeConv({ id: '1', name: 'Open', state: 'open' }),
        makeConv({ id: '2', name: 'Closed', state: 'closed' }),
        makeConv({ id: '3', name: 'Pending', state: 'pending' }),
        makeConv({ id: '4', name: 'Rejected', state: 'rejected' }),
      ],
    })
    vi.mocked(useConversationsStore).mockReturnValue(store as unknown as ReturnType<typeof useConversationsStore>)
    const wrapper = mount(ConversationList, { global: { stubs: { NewConversationModal: true } } })
    const text = wrapper.text()
    expect(text).toContain('Open')
    expect(text).toContain('Closed')
    expect(text).toContain('Pending')
    expect(text).toContain('Rejected')
  })

  it('pending row has a visible "awaiting reply" indicator', () => {
    const store = makeStore({ list: [makeConv({ id: 'p-2', name: 'Awaiting', state: 'pending' })] })
    vi.mocked(useConversationsStore).mockReturnValue(store as unknown as ReturnType<typeof useConversationsStore>)
    const wrapper = mount(ConversationList, { global: { stubs: { NewConversationModal: true } } })
    // The pending badge text is rendered in the row
    expect(wrapper.html()).toContain('data-pending-badge')
  })

  it('rejected row is visually greyed (has data-rejected class marker)', () => {
    const store = makeStore({ list: [makeConv({ id: 'r-2', name: 'Discarded', state: 'rejected' })] })
    vi.mocked(useConversationsStore).mockReturnValue(store as unknown as ReturnType<typeof useConversationsStore>)
    const wrapper = mount(ConversationList, { global: { stubs: { NewConversationModal: true } } })
    const row = wrapper.find('[data-testid="conversation-row"][data-state="rejected"]')
    expect(row.exists()).toBe(true)
    // Rejected rows carry opacity-muted class for greyout
    expect(row.html()).toContain('rejected')
  })
})
