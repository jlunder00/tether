import { describe, it, expect } from 'vitest'
import { mount } from '@vue/test-utils'
import MotifPicker from '../MotifPicker.vue'

const SLOTS = ['anchor','focus','calm','energy','care','flow','dusk','quiet','light','dark']

describe('MotifPicker', () => {
  it('renders 10 motif dots', () => {
    const wrapper = mount(MotifPicker, { props: { modelValue: null } })
    const dots = wrapper.findAll('[data-testid="motif-dot"]')
    expect(dots).toHaveLength(10)
    expect(dots.map(d => d.attributes('data-slot'))).toEqual(SLOTS)
  })

  it('emits update:modelValue with the clicked slot', async () => {
    const wrapper = mount(MotifPicker, { props: { modelValue: null } })
    await wrapper.find('[data-slot="focus"]').trigger('click')
    expect(wrapper.emitted('update:modelValue')).toBeTruthy()
    expect(wrapper.emitted('update:modelValue')![0]).toEqual(['focus'])
  })

  it('shows a ring/outline on the selected dot', () => {
    const wrapper = mount(MotifPicker, { props: { modelValue: 'calm' } })
    const selected = wrapper.find('[data-slot="calm"]')
    const style = selected.attributes('style') || ''
    expect(style).toContain('outline-color: var(--motif-calm)')
    expect(style).toContain('border-color: var(--motif-calm)')

    const unselected = wrapper.find('[data-slot="focus"]')
    const unstyle = unselected.attributes('style') || ''
    expect(unstyle).toContain('outline-style: none')
    expect(unstyle).toContain('border-color: transparent')
  })
})
