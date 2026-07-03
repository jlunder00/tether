import { describe, it, expect } from 'vitest'
import { mount } from '@vue/test-utils'
import MessageBubble from '../MessageBubble.vue'
import type { ChatMessage } from '../../types/chat'

function msg(overrides: Partial<ChatMessage> & Pick<ChatMessage, 'role' | 'content'>): ChatMessage {
  return { id: 'test-id', ts: Date.now(), ...overrides }
}

// ── Priority styling for system messages (Beacon D1) ─────────────────────────
describe('MessageBubble — system message priority', () => {
  it('normal priority (absent): renders as plain centered italic with no priority tint', () => {
    const wrapper = mount(MessageBubble, {
      props: { msg: msg({ role: 'system', content: 'Session started' }) },
    })
    // No priority tint classes
    expect(wrapper.html()).not.toContain('data-priority')
    // Still renders centered
    expect(wrapper.html()).toContain('text-center')
  })

  it('normal priority (explicit): same as absent — no tint', () => {
    const wrapper = mount(MessageBubble, {
      props: { msg: msg({ role: 'system', content: 'Info', priority: 'normal' }) },
    })
    expect(wrapper.html()).not.toContain('data-priority="important"')
    expect(wrapper.html()).not.toContain('data-priority="urgent"')
    expect(wrapper.html()).toContain('text-center')
  })

  it('important priority: renders tinted box with data-priority="important"', () => {
    const wrapper = mount(MessageBubble, {
      props: { msg: msg({ role: 'system', content: 'Anchor ping', priority: 'important' }) },
    })
    expect(wrapper.html()).toContain('data-priority="important"')
    expect(wrapper.text()).toContain('Anchor ping')
  })

  it('urgent priority: renders tinted box with data-priority="urgent"', () => {
    const wrapper = mount(MessageBubble, {
      props: { msg: msg({ role: 'system', content: 'Critical alert', priority: 'urgent' }) },
    })
    expect(wrapper.html()).toContain('data-priority="urgent"')
    expect(wrapper.text()).toContain('Critical alert')
  })

  it('important priority: renders ⏰ icon prefix (a11y: differentiable without color)', () => {
    const wrapper = mount(MessageBubble, {
      props: { msg: msg({ role: 'system', content: 'Time sensitive', priority: 'important' }) },
    })
    expect(wrapper.text()).toContain('⏰')
  })

  it('urgent priority: renders 🚨 icon prefix (a11y: differentiable without color)', () => {
    const wrapper = mount(MessageBubble, {
      props: { msg: msg({ role: 'system', content: 'Stop and look', priority: 'urgent' }) },
    })
    expect(wrapper.text()).toContain('🚨')
  })

  it('priority field on non-system message is ignored (no tint on user/bot)', () => {
    const userWrapper = mount(MessageBubble, {
      props: { msg: msg({ role: 'user', content: 'hello', priority: 'urgent' }) },
    })
    expect(userWrapper.html()).not.toContain('data-priority')

    const botWrapper = mount(MessageBubble, {
      props: { msg: msg({ role: 'bot', content: 'hi', priority: 'urgent' }) },
    })
    expect(botWrapper.html()).not.toContain('data-priority')
  })
})

describe('MessageBubble', () => {
  it('renders user message with right-align class', () => {
    const wrapper = mount(MessageBubble, { props: { msg: msg({ role: 'user', content: 'hello' }) } })
    expect(wrapper.text()).toContain('hello')
    expect(wrapper.html()).toContain('justify-end')
  })

  it('renders bot message with left-align class', () => {
    const wrapper = mount(MessageBubble, { props: { msg: msg({ role: 'bot', content: 'hi there' }) } })
    expect(wrapper.text()).toContain('hi there')
    expect(wrapper.html()).toContain('justify-start')
  })

  it('renders system message centered', () => {
    const wrapper = mount(MessageBubble, { props: { msg: msg({ role: 'system', content: 'Session started' }) } })
    expect(wrapper.text()).toContain('Session started')
    expect(wrapper.html()).toContain('text-center')
  })

  it('renders bot markdown bold as <strong>', () => {
    const wrapper = mount(MessageBubble, {
      props: { msg: msg({ role: 'bot', content: '**bold text**' }) },
    })
    expect(wrapper.find('strong').exists()).toBe(true)
    expect(wrapper.find('strong').text()).toBe('bold text')
  })

  it('renders user message as plain text (no html rendering)', () => {
    const wrapper = mount(MessageBubble, {
      props: { msg: msg({ role: 'user', content: '**not bold**' }) },
    })
    expect(wrapper.find('strong').exists()).toBe(false)
    expect(wrapper.text()).toContain('**not bold**')
  })

  it('does not render a blinking cursor', () => {
    const wrapper = mount(MessageBubble, {
      props: { msg: msg({ role: 'bot', content: 'text' }) },
    })
    // No streaming cursor since we dropped streaming state
    expect(wrapper.find('.cursor-blink').exists()).toBe(false)
    expect(wrapper.find('[data-cursor]').exists()).toBe(false)
  })
})
