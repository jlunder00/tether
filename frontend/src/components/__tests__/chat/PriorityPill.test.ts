import { describe, it, expect, beforeEach } from 'vitest'
import { mount } from '@vue/test-utils'
import { createPinia, setActivePinia } from 'pinia'
import PriorityPill from '../../chat/PriorityPill.vue'

describe('PriorityPill', () => {
  beforeEach(() => {
    setActivePinia(createPinia())
  })

  it('renders "low" priority', () => {
    const wrapper = mount(PriorityPill, { props: { priority: 'low' } })
    expect(wrapper.text().toLowerCase()).toContain('low')
  })

  it('renders "normal" priority', () => {
    const wrapper = mount(PriorityPill, { props: { priority: 'normal' } })
    expect(wrapper.text().toLowerCase()).toContain('normal')
  })

  it('renders "high" priority', () => {
    const wrapper = mount(PriorityPill, { props: { priority: 'high' } })
    expect(wrapper.text().toLowerCase()).toContain('high')
  })

  it('renders "urgent" priority', () => {
    const wrapper = mount(PriorityPill, { props: { priority: 'urgent' } })
    expect(wrapper.text().toLowerCase()).toContain('urgent')
  })

  it('emits change when clickable and clicked', async () => {
    const wrapper = mount(PriorityPill, { props: { priority: 'normal', clickable: true } })
    await wrapper.trigger('click')
    expect(wrapper.emitted('change')).toBeTruthy()
  })

  it('does not emit change when not clickable', async () => {
    const wrapper = mount(PriorityPill, { props: { priority: 'normal', clickable: false } })
    await wrapper.trigger('click')
    expect(wrapper.emitted('change')).toBeFalsy()
  })
})
