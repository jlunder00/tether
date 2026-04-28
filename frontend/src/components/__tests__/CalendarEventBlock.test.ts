import { describe, it, expect, vi, beforeEach } from 'vitest'
import { mount } from '@vue/test-utils'
import { createPinia, setActivePinia } from 'pinia'
import type { CalendarEvent } from '../../types/events'

vi.mock('vue-router', () => ({
  useRouter: () => ({ push: vi.fn() }),
  useRoute: () => ({ path: '/calendar' }),
}))

vi.mock('../../lib/api', () => ({
  api: vi.fn(() => Promise.resolve({ ok: true, json: async () => [] })),
}))

const baseEvent: CalendarEvent = {
  id: 'ev-1',
  title: 'Team standup',
  start_time: '2024-06-10T09:00:00Z',
  end_time: '2024-06-10T09:30:00Z',
  source: 'tether',
  external_id: null,
  task_id: null,
  anchor_id: null,
  color: null,
  is_recurring: false,
  is_occurrence: false,
  is_all_day: false,
  rrule: null,
  context_subject: null,
}

describe('CalendarEventBlock', () => {
  beforeEach(() => {
    setActivePinia(createPinia())
  })

  it('renders the event title', async () => {
    const { default: CalendarEventBlock } = await import('../CalendarEventBlock.vue')
    const wrapper = mount(CalendarEventBlock, {
      props: { event: baseEvent, topPx: 60, heightPx: 30 },
    })
    expect(wrapper.text()).toContain('Team standup')
  })

  it('applies topPx and heightPx as inline style', async () => {
    const { default: CalendarEventBlock } = await import('../CalendarEventBlock.vue')
    const wrapper = mount(CalendarEventBlock, {
      props: { event: baseEvent, topPx: 120, heightPx: 60 },
    })
    const style = wrapper.attributes('style') ?? ''
    expect(style).toContain('top: 120px')
    expect(style).toContain('height: 60px')
  })

  it('shows G badge for google_calendar source', async () => {
    const { default: CalendarEventBlock } = await import('../CalendarEventBlock.vue')
    const wrapper = mount(CalendarEventBlock, {
      props: {
        event: { ...baseEvent, source: 'google_calendar' },
        topPx: 0,
        heightPx: 30,
      },
    })
    expect(wrapper.text()).toContain('G')
  })

  it('does not show G badge for tether source', async () => {
    const { default: CalendarEventBlock } = await import('../CalendarEventBlock.vue')
    const wrapper = mount(CalendarEventBlock, {
      props: { event: baseEvent, topPx: 0, heightPx: 30 },
    })
    // The text 'G' should not appear as a standalone badge
    const badge = wrapper.find('[data-testid="gcal-badge"]')
    expect(badge.exists()).toBe(false)
  })

  it('emits click when clicked', async () => {
    const { default: CalendarEventBlock } = await import('../CalendarEventBlock.vue')
    const wrapper = mount(CalendarEventBlock, {
      props: { event: baseEvent, topPx: 0, heightPx: 30 },
    })
    await wrapper.trigger('click')
    expect(wrapper.emitted('click')).toBeTruthy()
  })

  // --- Recurring indicator tests ---

  it('shows recurring indicator when is_recurring is true', async () => {
    const { default: CalendarEventBlock } = await import('../CalendarEventBlock.vue')
    const wrapper = mount(CalendarEventBlock, {
      props: {
        event: { ...baseEvent, is_recurring: true },
        topPx: 0,
        heightPx: 30,
      },
    })
    expect(wrapper.find('[data-testid="recurring-indicator"]').exists()).toBe(true)
  })

  it('shows recurring indicator when is_occurrence is true', async () => {
    const { default: CalendarEventBlock } = await import('../CalendarEventBlock.vue')
    const wrapper = mount(CalendarEventBlock, {
      props: {
        event: { ...baseEvent, is_occurrence: true },
        topPx: 0,
        heightPx: 30,
      },
    })
    expect(wrapper.find('[data-testid="recurring-indicator"]').exists()).toBe(true)
  })

  it('does not show recurring indicator for non-recurring events', async () => {
    const { default: CalendarEventBlock } = await import('../CalendarEventBlock.vue')
    const wrapper = mount(CalendarEventBlock, {
      props: { event: baseEvent, topPx: 0, heightPx: 30 },
    })
    expect(wrapper.find('[data-testid="recurring-indicator"]').exists()).toBe(false)
  })

  it('positions event using leftPercent and widthPercent', async () => {
    const { default: CalendarEventBlock } = await import('../CalendarEventBlock.vue')
    const wrapper = mount(CalendarEventBlock, {
      props: {
        event: baseEvent, topPx: 100, heightPx: 60,
        leftPercent: 50, widthPercent: 50,
      },
    })
    const style = wrapper.attributes('style') ?? ''
    expect(style).toContain('50%')
  })

  it('uses resolvedColor when provided', async () => {
    const { default: CalendarEventBlock } = await import('../CalendarEventBlock.vue')
    const wrapper = mount(CalendarEventBlock, {
      props: {
        event: baseEvent, topPx: 0, heightPx: 30,
        resolvedColor: 'rgb(255, 0, 0)',
      },
    })
    const style = wrapper.attributes('style') ?? ''
    expect(style).toContain('rgb(255, 0, 0)')
  })
})
