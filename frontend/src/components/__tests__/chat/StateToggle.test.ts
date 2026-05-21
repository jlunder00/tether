import { describe, it, expect, beforeEach } from 'vitest'
import { mount } from '@vue/test-utils'
import { createPinia, setActivePinia } from 'pinia'
import StateToggle from '../../chat/StateToggle.vue'

describe('StateToggle', () => {
  beforeEach(() => {
    setActivePinia(createPinia())
  })

  it('renders open state text', () => {
    const wrapper = mount(StateToggle, { props: { state: 'open' } })
    expect(wrapper.text().toLowerCase()).toContain('open')
  })

  it('renders closed state text', () => {
    const wrapper = mount(StateToggle, { props: { state: 'closed' } })
    expect(wrapper.text().toLowerCase()).toContain('closed')
  })

  it('emits change with toggled state when open', async () => {
    const wrapper = mount(StateToggle, { props: { state: 'open' } })
    await wrapper.trigger('click')
    expect(wrapper.emitted('change')).toBeTruthy()
    expect(wrapper.emitted('change')![0]).toEqual(['closed'])
  })

  it('emits change with toggled state when closed', async () => {
    const wrapper = mount(StateToggle, { props: { state: 'closed' } })
    await wrapper.trigger('click')
    expect(wrapper.emitted('change')).toBeTruthy()
    expect(wrapper.emitted('change')![0]).toEqual(['open'])
  })

  it('does not emit when loading', async () => {
    const wrapper = mount(StateToggle, { props: { state: 'open', loading: true } })
    await wrapper.trigger('click')
    expect(wrapper.emitted('change')).toBeFalsy()
  })
})
