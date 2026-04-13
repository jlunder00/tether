import { describe, it, expect } from 'vitest'
import { mount } from '@vue/test-utils'
import { defineComponent } from 'vue'

describe('vitest setup', () => {
  it('can mount a Vue component', () => {
    const Comp = defineComponent({ template: '<div>hello</div>' })
    const wrapper = mount(Comp)
    expect(wrapper.text()).toBe('hello')
  })
})
