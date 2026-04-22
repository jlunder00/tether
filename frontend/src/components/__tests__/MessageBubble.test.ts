import { describe, it, expect } from 'vitest'
import { mount } from '@vue/test-utils'
import MessageBubble from '../MessageBubble.vue'
import type { ChatMessage } from '../../types/chat'

function msg(overrides: Partial<ChatMessage> & Pick<ChatMessage, 'role' | 'content'>): ChatMessage {
  return { id: 'test-id', ts: Date.now(), ...overrides }
}

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
