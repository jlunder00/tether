/**
 * CalendarView — event block click navigation
 *
 * Regression test for duplicate panel bug:
 *   Clicking a calendar event used to call pushPanel twice because
 *   TaskCard's own @click.stop AND CalendarView's @click="openEventPanel"
 *   (a Vue 3 fallthrough attribute) both fired on the same root element.
 *   stopPropagation prevents bubbling, not same-element merged listeners.
 *
 * These tests verify:
 *   1. Clicking a task-backed event pushes exactly one panel with kind:'task'
 *   2. Clicking a standalone event (no task_id) pushes exactly one panel with kind:'event'
 */
import { describe, it, expect, vi, beforeEach, defineComponent } from 'vitest'
import { mount, flushPromises } from '@vue/test-utils'
import { createPinia, setActivePinia } from 'pinia'
import { nextTick } from 'vue'
import { resetFocusedDay } from '../../composables/useCalendarFocus'

// ── Mocks ──────────────────────────────────────────────────────────────────────

const replaceMock = vi.fn()
const pushPanelMock = vi.fn()

vi.mock('vue-router', () => ({
  useRouter: () => ({ push: vi.fn(), back: vi.fn(), replace: replaceMock }),
  useRoute: () => ({ path: '/calendar', query: {} }),
  RouterLink: {
    props: ['to'],
    template: '<a><slot /></a>',
  },
  RouterView: { template: '<div />' },
}))

vi.mock('../../lib/api', () => ({
  api: vi.fn(() => Promise.resolve({ ok: true, json: async () => [] })),
}))

// Mock useSlideOver so both CalendarView and TaskCard share the same push spy.
vi.mock('../../composables/useSlideOver', () => ({
  useSlideOver: () => ({
    stack: { value: [] },
    push: pushPanelMock,
    pop: vi.fn(),
    close: vi.fn(),
    restoreFromUrl: vi.fn(),
  }),
  resetSlideOverStack: vi.fn(),
}))

// ── Helpers ────────────────────────────────────────────────────────────────────

function localDateString(d: Date): string {
  return `${d.getFullYear()}-${String(d.getMonth() + 1).padStart(2, '0')}-${String(d.getDate()).padStart(2, '0')}`
}

const TODAY = localDateString(new Date())

// ── Tests ──────────────────────────────────────────────────────────────────────

describe('CalendarView — calendar event block click', () => {
  beforeEach(() => {
    setActivePinia(createPinia())
    resetFocusedDay()
    pushPanelMock.mockReset()
    replaceMock.mockReset()
  })

  it('clicking a task-backed event block calls pushPanel exactly once with kind:task', async () => {
    const { useEventStore } = await import('../../stores/events')
    const { default: CalendarView } = await import('../CalendarView.vue')

    const wrapper = mount(CalendarView)
    await flushPromises()

    useEventStore().events.push({
      id: 'ev-task1',
      title: 'My Task Event',
      start_time: `${TODAY}T09:00:00`,
      end_time: `${TODAY}T10:00:00`,
      source: 'tether',
      external_id: null,
      task_id: 'task-abc',
      anchor_id: null,
      color: null,
      is_recurring: false,
      is_occurrence: false,
      is_all_day: false,
      rrule: null,
      context_subject: null,
    })
    await nextTick()

    const eventBlock = wrapper.find('[data-testid="task-card-calendar-event"]')
    expect(eventBlock.exists()).toBe(true)

    await eventBlock.trigger('click')

    // Must be called exactly once — the bug causes it to be called twice
    expect(pushPanelMock).toHaveBeenCalledTimes(1)
    expect(pushPanelMock).toHaveBeenCalledWith({ kind: 'task', entityId: 'task-abc' })
  })

  it('clicking a standalone event block (no task_id) calls pushPanel once with kind:event', async () => {
    const { useEventStore } = await import('../../stores/events')
    const { default: CalendarView } = await import('../CalendarView.vue')

    const wrapper = mount(CalendarView)
    await flushPromises()

    useEventStore().events.push({
      id: 'ev-standalone',
      title: 'Standalone GCal Event',
      start_time: `${TODAY}T14:00:00`,
      end_time: `${TODAY}T15:00:00`,
      source: 'google_calendar',
      external_id: 'gcal-xyz',
      task_id: null,
      anchor_id: null,
      color: null,
      is_recurring: false,
      is_occurrence: false,
      is_all_day: false,
      rrule: null,
      context_subject: null,
    })
    await nextTick()

    const eventBlock = wrapper.find('[data-testid="task-card-calendar-event"]')
    expect(eventBlock.exists()).toBe(true)

    await eventBlock.trigger('click')

    // Standalone events must use kind:'event', not kind:'task'
    expect(pushPanelMock).toHaveBeenCalledTimes(1)
    expect(pushPanelMock).toHaveBeenCalledWith({ kind: 'event', entityId: 'ev-standalone' })
  })
})
