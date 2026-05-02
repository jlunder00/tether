/**
 * DayTimeline — 15-min slot drop targets (Track 2, calendar HTML5 DnD refactor)
 *
 * These tests cover the new drop-zone behaviour added by the DnD unification.
 *
 * Scenarios:
 *   1. Each 15-min time slot renders a drop target element with data-date + data-time
 *   2. Dropping a task payload onto a slot promotes it to an event at that time
 *   3. Dropping a calendar-event payload onto a slot moves the event (duration preserved)
 *   4. Source element of the dragged event is hidden (isDragging = true → v-show=false)
 *      while drag is in progress, restored on dragend
 *   5. Drop on an occupied slot (existing event) moves the existing event rather than
 *      creating a duplicate
 *   6. dragover on a slot sets isOver=true (highlight); dragleave clears it
 */
import { describe, it, expect, vi, beforeEach } from 'vitest'
import { mount } from '@vue/test-utils'
import { createPinia, setActivePinia } from 'pinia'
import { AXIS_START_HOUR, AXIS_END_HOUR } from '../../composables/useDayTimeline'
import type { CalendarEvent } from '../../types/events'

// --- Mocks (same setup as DayTimeline.test.ts) ---

vi.mock('vue-router', () => ({
  useRouter: () => ({ push: vi.fn() }),
  useRoute: () => ({ path: '/plan/day', query: {} }),
  RouterLink: { template: '<a><slot /></a>' },
}))

vi.mock('../../lib/api', () => ({
  api: vi.fn(() => Promise.resolve({ ok: true, json: async () => [] })),
}))

const mockPromoteTask = vi.fn()
const mockMoveEvent = vi.fn()

const mockTimedEvent: CalendarEvent = {
  id: 'ev-timed',
  title: 'Team standup',
  start_time: '2024-06-10T09:00:00',
  end_time: '2024-06-10T09:30:00',
  source: 'tether',
  external_id: null,
  task_id: 'task-1',
  anchor_id: null,
  color: null,
  is_recurring: false,
  is_occurrence: false,
  rrule: null,
  is_all_day: false,
  context_subject: null,
}

const mockEvents: CalendarEvent[] = [mockTimedEvent]

vi.mock('../../stores/anchors', () => ({
  useAnchorStore: () => ({
    anchors: [],
    fetchAnchors: vi.fn(),
  }),
}))

vi.mock('../../stores/events', () => ({
  useEventStore: () => ({
    events: mockEvents,
    loading: false,
    fetchEvents: vi.fn(),
    moveEvent: mockMoveEvent,
    promoteTask: mockPromoteTask,
    demoteEvent: vi.fn(),
    createTaskAndPromote: vi.fn(),
  }),
}))

vi.mock('../../stores/milestones', () => ({
  useMilestoneStore: () => ({
    all: [],
    fetchAll: vi.fn(),
  }),
}))

vi.mock('../../stores/context', () => ({
  useContextStore: () => ({
    nodes: {},
  }),
}))

// Expected total 15-min slots
const TOTAL_SLOTS = (AXIS_END_HOUR - AXIS_START_HOUR) * 4  // 72

// --- Tests ---

describe('DayTimeline – 15-min slot drop targets', () => {
  beforeEach(() => {
    setActivePinia(createPinia())
    mockPromoteTask.mockReset()
    mockMoveEvent.mockReset()
  })

  it('each 15-min slot has data-date and data-time attributes', async () => {
    const { default: DayTimeline } = await import('../DayTimeline.vue')
    const wrapper = mount(DayTimeline, { props: { date: '2024-06-10' } })
    const slots = wrapper.findAll('[data-time-slot]')
    expect(slots.length).toBe(TOTAL_SLOTS)
    // Spot-check first slot: 06:00
    const first = slots[0]
    expect(first.attributes('data-date')).toBe('2024-06-10')
    expect(first.attributes('data-time')).toBe('06:00')
    // Spot-check last slot: 23:45
    const last = slots[slots.length - 1]
    expect(last.attributes('data-date')).toBe('2024-06-10')
    expect(last.attributes('data-time')).toBe('23:45')
  })

  it('dropping a task payload promotes it to an event at the slot time (30min default duration)', async () => {
    const { default: DayTimeline } = await import('../DayTimeline.vue')
    const wrapper = mount(DayTimeline, { props: { date: '2024-06-10' } })
    // Find the 09:00 slot
    const slot = wrapper.find('[data-time="09:00"]')
    expect(slot.exists()).toBe(true)
    const payload = { type: 'task', taskId: 'task-99', title: 'Do the thing' }
    await slot.trigger('drop', { dataTransfer: { getData: (t: string) => t === 'application/json' ? JSON.stringify(payload) : '' } })
    expect(mockPromoteTask).toHaveBeenCalledWith(
      'task-99',
      expect.stringContaining('09:00'),
      expect.stringContaining('09:30'),
      'Do the thing',
    )
  })

  it('dropping a calendar-event payload moves the event preserving duration (PATCH /api/events/:id)', async () => {
    const { default: DayTimeline } = await import('../DayTimeline.vue')
    const wrapper = mount(DayTimeline, { props: { date: '2024-06-10' } })
    const slot = wrapper.find('[data-time="10:00"]')
    expect(slot.exists()).toBe(true)
    const durationMs = 30 * 60_000  // 30 min
    const payload = {
      type: 'calendar-event',
      eventId: 'ev-timed',
      title: 'Team standup',
      fromStartTime: '2024-06-10T09:00:00',
      durationMs,
    }
    await slot.trigger('drop', { dataTransfer: { getData: (t: string) => t === 'application/json' ? JSON.stringify(payload) : '' } })
    expect(mockMoveEvent).toHaveBeenCalledWith(
      'ev-timed',
      expect.stringContaining('10:00'),
      expect.stringContaining('10:30'),
    )
  })

  it('source event block is hidden (v-show=false) while its drag is active', async () => {
    const { default: DayTimeline } = await import('../DayTimeline.vue')
    // attachTo: document.body required for v-show to propagate in jsdom
    const wrapper = mount(DayTimeline, { props: { date: '2024-06-10' }, attachTo: document.body })
    // Find the event wrapper (has data-event-id)
    const eventWrapper = wrapper.find(`[data-event-id="${mockTimedEvent.id}"]`)
    expect(eventWrapper.exists()).toBe(true)
    // Initially visible
    expect(eventWrapper.isVisible()).toBe(true)
    // Trigger dragstart on the event element
    await eventWrapper.trigger('dragstart')
    await wrapper.vm.$nextTick()
    expect(eventWrapper.isVisible()).toBe(false)
    wrapper.unmount()
  })

  it('source event block is restored (v-show=true) on dragend with no valid drop', async () => {
    const { default: DayTimeline } = await import('../DayTimeline.vue')
    const wrapper = mount(DayTimeline, { props: { date: '2024-06-10' }, attachTo: document.body })
    const eventWrapper = wrapper.find(`[data-event-id="${mockTimedEvent.id}"]`)
    await eventWrapper.trigger('dragstart')
    await wrapper.vm.$nextTick()
    // Now fire dragend
    await eventWrapper.trigger('dragend')
    await wrapper.vm.$nextTick()
    expect(eventWrapper.isVisible()).toBe(true)
    wrapper.unmount()
  })

  it('drop highlight (isOver) is applied to the hovered slot and cleared on dragleave', async () => {
    const { default: DayTimeline } = await import('../DayTimeline.vue')
    const wrapper = mount(DayTimeline, { props: { date: '2024-06-10' } })
    const slot = wrapper.find('[data-time="09:00"]')
    await slot.trigger('dragover')
    await wrapper.vm.$nextTick()
    // Should have the over-highlight class
    expect(slot.classes()).toContain('ring-1')
    await slot.trigger('dragleave')
    await wrapper.vm.$nextTick()
    expect(slot.classes()).not.toContain('ring-1')
  })

  it('dropping an already-promoted task moves the existing event rather than creating a duplicate', async () => {
    // mockTimedEvent has task_id = 'task-1'; dropping 'task-1' should call moveEvent, not promoteTask
    const { default: DayTimeline } = await import('../DayTimeline.vue')
    const wrapper = mount(DayTimeline, { props: { date: '2024-06-10' } })
    const slot = wrapper.find('[data-time="11:00"]')
    const payload = { type: 'task', taskId: 'task-1', title: 'Team standup' }
    await slot.trigger('drop', { dataTransfer: { getData: (t: string) => t === 'application/json' ? JSON.stringify(payload) : '' } })
    expect(mockMoveEvent).toHaveBeenCalled()
    expect(mockPromoteTask).not.toHaveBeenCalled()
  })
})
