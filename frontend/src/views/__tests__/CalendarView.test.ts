import { describe, it, expect, vi, beforeEach } from 'vitest'
import { mount } from '@vue/test-utils'
import { createPinia, setActivePinia } from 'pinia'
import { defineComponent, h } from 'vue'

// Lightweight stub for router-link so we can test nav rendering
vi.mock('vue-router', () => ({
  useRouter: () => ({ push: vi.fn(), back: vi.fn() }),
  useRoute: () => ({ path: '/calendar', query: {} }),
  RouterLink: defineComponent({
    props: ['to'],
    setup(props, { slots }) {
      return () => h('a', { href: typeof props.to === 'string' ? props.to : props.to?.path ?? '#' }, slots.default?.())
    },
  }),
  RouterView: defineComponent({ template: '<div />' }),
}))

// Stub API so store actions don't fire real requests
vi.mock('../../lib/api', () => ({
  api: vi.fn(() => Promise.resolve({ ok: true, json: async () => [] })),
}))

describe('CalendarView', () => {
  beforeEach(() => {
    setActivePinia(createPinia())
  })

  it('renders a top-level heading with "Calendar"', async () => {
    const { default: CalendarView } = await import('../CalendarView.vue')
    const wrapper = mount(CalendarView)
    expect(wrapper.text()).toMatch(/Calendar/i)
  })

  it('renders the week time-grid container', async () => {
    const { default: CalendarView } = await import('../CalendarView.vue')
    const wrapper = mount(CalendarView)
    // The grid must exist in the DOM — identified by data-testid
    expect(wrapper.find('[data-testid="calendar-grid"]').exists()).toBe(true)
  })

  it('renders an anchor panel section', async () => {
    const { default: CalendarView } = await import('../CalendarView.vue')
    const wrapper = mount(CalendarView)
    expect(wrapper.find('[data-testid="anchor-panel"]').exists()).toBe(true)
  })

  it('can collapse and expand the anchor panel', async () => {
    const { default: CalendarView } = await import('../CalendarView.vue')
    const wrapper = mount(CalendarView)
    const toggle = wrapper.find('[data-testid="anchor-panel-toggle"]')
    expect(toggle.exists()).toBe(true)
    await toggle.trigger('click')
    expect(wrapper.find('[data-testid="anchor-panel-content"]').exists()).toBe(false)
    await toggle.trigger('click')
    expect(wrapper.find('[data-testid="anchor-panel-content"]').exists()).toBe(true)
  })
})
