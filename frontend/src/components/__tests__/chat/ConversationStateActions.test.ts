/**
 * Tests for ConversationStateActions — Beacon wave 7, D1.
 *
 * This component renders appropriate action buttons based on conversation state:
 *   pending  → "Approve" (→ open) + "Dismiss" (→ rejected)
 *   rejected → "Restore" (→ open)
 *   open     → overflow "Mark as rejected" option
 *   closed   → no actions (archive state)
 *
 * The component emits state-change events; the parent calls store.patch().
 * This keeps the component pure and testable without store mocking.
 */
import { describe, it, expect, vi, beforeEach } from 'vitest'
import { mount } from '@vue/test-utils'
import { createPinia, setActivePinia } from 'pinia'
import ConversationStateActions from '../../chat/ConversationStateActions.vue'

describe('ConversationStateActions — pending state', () => {
  beforeEach(() => {
    setActivePinia(createPinia())
  })

  it('renders Approve and Dismiss buttons for a pending conversation', () => {
    const wrapper = mount(ConversationStateActions, {
      props: { state: 'pending', convId: 'conv-1' },
    })
    const text = wrapper.text().toLowerCase()
    expect(text).toContain('approve')
    expect(text).toContain('dismiss')
  })

  it('Approve button has data-testid="btn-approve"', () => {
    const wrapper = mount(ConversationStateActions, {
      props: { state: 'pending', convId: 'conv-1' },
    })
    expect(wrapper.find('[data-testid="btn-approve"]').exists()).toBe(true)
  })

  it('Dismiss button has data-testid="btn-dismiss"', () => {
    const wrapper = mount(ConversationStateActions, {
      props: { state: 'pending', convId: 'conv-1' },
    })
    expect(wrapper.find('[data-testid="btn-dismiss"]').exists()).toBe(true)
  })

  it('clicking Approve emits approve event', async () => {
    const wrapper = mount(ConversationStateActions, {
      props: { state: 'pending', convId: 'conv-1' },
    })
    await wrapper.find('[data-testid="btn-approve"]').trigger('click')
    expect(wrapper.emitted('approve')).toBeTruthy()
    expect(wrapper.emitted('approve')![0]).toEqual(['conv-1'])
  })

  it('clicking Dismiss emits dismiss event', async () => {
    const wrapper = mount(ConversationStateActions, {
      props: { state: 'pending', convId: 'conv-1' },
    })
    await wrapper.find('[data-testid="btn-dismiss"]').trigger('click')
    expect(wrapper.emitted('dismiss')).toBeTruthy()
    expect(wrapper.emitted('dismiss')![0]).toEqual(['conv-1'])
  })

  it('Approve button is disabled when loading=true', async () => {
    const wrapper = mount(ConversationStateActions, {
      props: { state: 'pending', convId: 'conv-1', loading: true },
    })
    const approveBtn = wrapper.find('[data-testid="btn-approve"]')
    expect(approveBtn.attributes('disabled')).toBeDefined()
  })

  it('Dismiss button is disabled when loading=true', async () => {
    const wrapper = mount(ConversationStateActions, {
      props: { state: 'pending', convId: 'conv-1', loading: true },
    })
    const dismissBtn = wrapper.find('[data-testid="btn-dismiss"]')
    expect(dismissBtn.attributes('disabled')).toBeDefined()
  })

  it('does NOT render Restore button for pending', () => {
    const wrapper = mount(ConversationStateActions, {
      props: { state: 'pending', convId: 'conv-1' },
    })
    expect(wrapper.find('[data-testid="btn-restore"]').exists()).toBe(false)
  })
})

describe('ConversationStateActions — rejected state', () => {
  beforeEach(() => {
    setActivePinia(createPinia())
  })

  it('renders Restore button for a rejected conversation', () => {
    const wrapper = mount(ConversationStateActions, {
      props: { state: 'rejected', convId: 'conv-2' },
    })
    expect(wrapper.text().toLowerCase()).toContain('restore')
  })

  it('Restore button has data-testid="btn-restore"', () => {
    const wrapper = mount(ConversationStateActions, {
      props: { state: 'rejected', convId: 'conv-2' },
    })
    expect(wrapper.find('[data-testid="btn-restore"]').exists()).toBe(true)
  })

  it('clicking Restore emits restore event with convId', async () => {
    const wrapper = mount(ConversationStateActions, {
      props: { state: 'rejected', convId: 'conv-2' },
    })
    await wrapper.find('[data-testid="btn-restore"]').trigger('click')
    expect(wrapper.emitted('restore')).toBeTruthy()
    expect(wrapper.emitted('restore')![0]).toEqual(['conv-2'])
  })

  it('does NOT render Approve or Dismiss for rejected', () => {
    const wrapper = mount(ConversationStateActions, {
      props: { state: 'rejected', convId: 'conv-2' },
    })
    expect(wrapper.find('[data-testid="btn-approve"]').exists()).toBe(false)
    expect(wrapper.find('[data-testid="btn-dismiss"]').exists()).toBe(false)
  })
})

describe('ConversationStateActions — open state', () => {
  beforeEach(() => {
    setActivePinia(createPinia())
  })

  it('renders a "Mark as rejected" overflow option for open conversations', () => {
    const wrapper = mount(ConversationStateActions, {
      props: { state: 'open', convId: 'conv-3' },
    })
    // The overflow button should exist
    expect(wrapper.find('[data-testid="btn-overflow"]').exists()).toBe(true)
  })

  it('clicking overflow exposes Mark-as-rejected option', async () => {
    const wrapper = mount(ConversationStateActions, {
      props: { state: 'open', convId: 'conv-3' },
    })
    await wrapper.find('[data-testid="btn-overflow"]').trigger('click')
    expect(wrapper.find('[data-testid="btn-mark-rejected"]').exists()).toBe(true)
  })

  it('clicking Mark-as-rejected emits dismiss event', async () => {
    const wrapper = mount(ConversationStateActions, {
      props: { state: 'open', convId: 'conv-3' },
    })
    await wrapper.find('[data-testid="btn-overflow"]').trigger('click')
    await wrapper.find('[data-testid="btn-mark-rejected"]').trigger('click')
    expect(wrapper.emitted('dismiss')).toBeTruthy()
    expect(wrapper.emitted('dismiss')![0]).toEqual(['conv-3'])
  })

  it('does NOT render Approve, Dismiss, or Restore inline for open', () => {
    const wrapper = mount(ConversationStateActions, {
      props: { state: 'open', convId: 'conv-3' },
    })
    expect(wrapper.find('[data-testid="btn-approve"]').exists()).toBe(false)
    expect(wrapper.find('[data-testid="btn-dismiss"]').exists()).toBe(false)
    expect(wrapper.find('[data-testid="btn-restore"]').exists()).toBe(false)
  })
})

describe('ConversationStateActions — closed state', () => {
  beforeEach(() => {
    setActivePinia(createPinia())
  })

  it('renders nothing meaningful for closed conversations (archive state)', () => {
    const wrapper = mount(ConversationStateActions, {
      props: { state: 'closed', convId: 'conv-4' },
    })
    // No action buttons for closed/archived convs
    expect(wrapper.find('[data-testid="btn-approve"]').exists()).toBe(false)
    expect(wrapper.find('[data-testid="btn-dismiss"]').exists()).toBe(false)
    expect(wrapper.find('[data-testid="btn-restore"]').exists()).toBe(false)
  })
})
