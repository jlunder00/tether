import { describe, it, expect, vi, beforeEach } from 'vitest'
import { mount } from '@vue/test-utils'
import { createPinia, setActivePinia } from 'pinia'
import NewConversationModal from '../../chat/NewConversationModal.vue'

vi.mock('../../../lib/api', () => ({ api: vi.fn() }))
vi.mock('../../../stores/conversations', () => ({
  useConversationsStore: vi.fn(() => ({
    create: vi.fn().mockResolvedValue({
      id: 'new-conv',
      name: 'Test',
      type: 'interactive',
      priority: 'normal',
      state: 'open',
      context_node_id: null,
      thread_key: null,
      is_system: false,
      created_at: '2026-01-01T00:00:00Z',
      last_message_at: '2026-01-01T00:00:00Z',
      folder_name: null,
    }),
  })),
}))

import { useConversationsStore } from '../../../stores/conversations'

describe('NewConversationModal', () => {
  beforeEach(() => {
    setActivePinia(createPinia())
    vi.mocked(useConversationsStore).mockReturnValue({
      create: vi.fn().mockResolvedValue({
        id: 'new-conv',
        name: 'Test',
        type: 'interactive',
        priority: 'normal',
        state: 'open',
        context_node_id: null,
        thread_key: null,
        is_system: false,
        created_at: '2026-01-01T00:00:00Z',
        last_message_at: '2026-01-01T00:00:00Z',
        folder_name: null,
      }),
    } as unknown as ReturnType<typeof useConversationsStore>)
  })

  it('does not render when open is false', () => {
    const wrapper = mount(NewConversationModal, {
      props: { open: false, contextNodes: [] },
    })
    expect(wrapper.find('form').exists()).toBe(false)
  })

  it('renders form when open', () => {
    const wrapper = mount(NewConversationModal, {
      props: { open: true, contextNodes: [] },
    })
    expect(wrapper.find('form').exists()).toBe(true)
  })

  it('submit button is disabled when name is empty', () => {
    const wrapper = mount(NewConversationModal, {
      props: { open: true, contextNodes: [] },
    })
    const btn = wrapper.find('button[type="submit"]')
    expect((btn.element as HTMLButtonElement).disabled).toBe(true)
  })

  it('submit button enabled when name is filled', async () => {
    const wrapper = mount(NewConversationModal, {
      props: { open: true, contextNodes: [] },
    })
    await wrapper.find('input[type="text"]').setValue('My conversation')
    const btn = wrapper.find('button[type="submit"]')
    expect((btn.element as HTMLButtonElement).disabled).toBe(false)
  })

  it('calls store.create on submit and emits created and close', async () => {
    const wrapper = mount(NewConversationModal, {
      props: { open: true, contextNodes: [] },
    })
    await wrapper.find('input[type="text"]').setValue('Test')
    await wrapper.find('form').trigger('submit')
    await new Promise(r => setTimeout(r, 10))

    const store = useConversationsStore()
    expect(store.create).toHaveBeenCalledWith(expect.objectContaining({ name: 'Test' }))
    expect(wrapper.emitted('created')).toBeTruthy()
    expect(wrapper.emitted('close')).toBeTruthy()
  })

  it('emits close when X button clicked', async () => {
    const wrapper = mount(NewConversationModal, {
      props: { open: true, contextNodes: [] },
    })
    await wrapper.find('button[aria-label="Close modal"]').trigger('click')
    expect(wrapper.emitted('close')).toBeTruthy()
  })
})
