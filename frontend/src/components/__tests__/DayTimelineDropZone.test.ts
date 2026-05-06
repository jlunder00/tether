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
const mockFetchPlan = vi.fn()

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

vi.mock('../../stores/plan', () => ({
  usePlanStore: () => ({
    plan: null,
    plans: {},
    fetchPlan: mockFetchPlan,
    today: '2024-06-10',
    activeDate: { value: '2024-06-10' },
  }),
}))

vi.mock('../../composables/useSlideOver', () => ({
  useSlideOver: () => ({
    stack: { value: [] },
    push: vi.fn(),
    pop: vi.fn(),
    close: vi.fn(),
    restoreFromUrl: vi.fn(),
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
    mockFetchPlan.mockReset()
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

  it('after promoting a task to calendar, planStore.fetchPlan is called to refresh the plan cache', async () => {
    // Bug 1: promoteTask runs but plan cache is never refreshed, so the task stays visible in the anchor block
    const { default: DayTimeline } = await import('../DayTimeline.vue')
    const wrapper = mount(DayTimeline, { props: { date: '2024-06-10' } })
    const slot = wrapper.find('[data-time="09:00"]')
    const payload = { type: 'task', taskId: 'task-99', title: 'Do the thing' }
    await slot.trigger('drop', { dataTransfer: { getData: (t: string) => t === 'application/json' ? JSON.stringify(payload) : '' } })
    expect(mockPromoteTask).toHaveBeenCalled()
    expect(mockFetchPlan).toHaveBeenCalledWith('2024-06-10')
  })

  it('dropping a task payload with fromStartTime moves the event preserving duration (PATCH /api/events/:id)', async () => {
    const { default: DayTimeline } = await import('../DayTimeline.vue')
    const wrapper = mount(DayTimeline, { props: { date: '2024-06-10' } })
    const slot = wrapper.find('[data-time="10:00"]')
    expect(slot.exists()).toBe(true)
    const durationMs = 30 * 60_000  // 30 min
    // After migration: TaskCard writes type:'task' not type:'calendar-event'
    const payload = {
      type: 'task',
      taskId: 'task-1',  // mockTimedEvent.task_id = 'task-1'
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
    const wrapper = mount(DayTimeline, { props: { date: '2024-06-10' }, attachTo: document.body })
    const card = wrapper.find('[data-testid="task-card-calendar-event"]')
    expect(card.exists()).toBe(true)
    expect(card.isVisible()).toBe(true)
    await card.trigger('dragstart', {
      dataTransfer: { setData: vi.fn(), effectAllowed: '' },
    })
    // useDraggableTask defers isDragging=true to rAF for ghost-image capture
    await new Promise(r => requestAnimationFrame(r))
    await wrapper.vm.$nextTick()
    expect(card.isVisible()).toBe(false)
    wrapper.unmount()
  })

  it('source event block is restored (v-show=true) on dragend with no valid drop', async () => {
    const { default: DayTimeline } = await import('../DayTimeline.vue')
    const wrapper = mount(DayTimeline, { props: { date: '2024-06-10' }, attachTo: document.body })
    const card = wrapper.find('[data-testid="task-card-calendar-event"]')
    await card.trigger('dragstart', {
      dataTransfer: { setData: vi.fn(), effectAllowed: '' },
    })
    await new Promise(r => requestAnimationFrame(r))
    await wrapper.vm.$nextTick()
    await card.trigger('dragend')
    await wrapper.vm.$nextTick()
    expect(card.isVisible()).toBe(true)
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

  // ── Bug B: drops that land on a TaskCard (above slot divs in z-order) must still work ──
  it('dropping a task payload onto the timed-area container (over an event block) promotes it correctly', async () => {
    // Bug B: TaskCards sit above slot divs in DOM/z-order. Drops over them bubble up
    // to the timed-area container. The container must handle them via clientY computation.
    const { default: DayTimeline } = await import('../DayTimeline.vue')
    const wrapper = mount(DayTimeline, { props: { date: '2024-06-10' } })
    const timedArea = wrapper.find('[data-testid="timed-area"]')
    expect(timedArea.exists()).toBe(true)
    const payload = { type: 'task', taskId: 'task-99', title: 'Dropped over event block' }
    await timedArea.trigger('drop', {
      dataTransfer: { getData: (t: string) => t === 'text/plain' ? JSON.stringify(payload) : '' },
    })
    // task-99 has no existing event → promoteTask
    expect(mockPromoteTask).toHaveBeenCalledWith(
      'task-99',
      expect.any(String),
      expect.any(String),
      'Dropped over event block',
    )
  })

  // ── Slot position accuracy: regression test for slotIndexFromClientY math ──
  it('onTimedAreaDrop maps clientY to the correct 15-min slot using rect.top + scrollTop', async () => {
    // Mocks getBoundingClientRect so the formula can be exercised with known values.
    // clientY=190, rect.top=100, scrollTop=0 → relY=90 → slot4 (90/22.5=4) → 07:00
    const { default: DayTimeline } = await import('../DayTimeline.vue')
    const wrapper = mount(DayTimeline, { props: { date: '2024-06-10' }, attachTo: document.body })
    const timedArea = wrapper.find('[data-testid="timed-area"]')
    const el = timedArea.element as HTMLElement

    vi.spyOn(el, 'getBoundingClientRect').mockReturnValue({
      top: 100, left: 0, right: 320, bottom: 800, width: 320, height: 700,
      x: 0, y: 100, toJSON: () => ({}),
    } as DOMRect)
    Object.defineProperty(el, 'scrollTop', { value: 0, configurable: true, writable: true })

    const payload = { type: 'task', taskId: 'task-99', title: 'X' }
    await timedArea.trigger('drop', {
      clientY: 190,
      dataTransfer: { getData: (t: string) => t === 'text/plain' ? JSON.stringify(payload) : '' },
    })
    expect(mockPromoteTask).toHaveBeenCalledWith(
      'task-99',
      expect.stringContaining('T07:00'),
      expect.stringContaining('T07:30'),
      'X',
    )
    wrapper.unmount()
  })

  // ── overSlotIndex path: slot div dragover sets exact index, container drop uses it ──
  it('drop on timed-area container uses overSlotIndex set by slot dragover (no clientY math)', async () => {
    // When pointer-events-none makes TaskCards transparent, drops land on the underlying
    // slot div — but the drop event bubbles up to the container. The container must use
    // overSlotIndex (set by that slot's @dragover handler) rather than slotIndexFromClientY
    // which depends on getBoundingClientRect/scrollTop and can give wrong results when scrolled.
    //
    // Flow: dragenter → dragover on [data-time="09:00"] → drop on timed-area (no clientY)
    // Expected: promoteTask called with 09:00/09:30 (slot 12), not 06:00 (slot 0 fallback).
    const { default: DayTimeline } = await import('../DayTimeline.vue')
    const wrapper = mount(DayTimeline, { props: { date: '2024-06-10' }, attachTo: document.body })
    const timedArea = wrapper.find('[data-testid="timed-area"]')

    // Step 1: drag enters the timed area (sets dragActive=true)
    await timedArea.trigger('dragenter', { dataTransfer: { types: ['text/plain'] } })
    await wrapper.vm.$nextTick()

    // Step 2: drag moves over the 09:00 slot div (sets overSlotIndex via onSlotDragOver)
    const slot = wrapper.find('[data-time="09:00"]')
    expect(slot.exists()).toBe(true)
    await slot.trigger('dragover')
    await wrapper.vm.$nextTick()

    // Step 3: drop on the container (no clientY — would give slot 0 via slotIndexFromClientY)
    const payload = { type: 'task', taskId: 'task-99', title: 'overSlotIndex test' }
    await timedArea.trigger('drop', {
      clientY: 0,  // would map to slot 0 (06:00) via slotIndexFromClientY — wrong answer
      dataTransfer: { getData: (t: string) => t === 'text/plain' ? JSON.stringify(payload) : '' },
    })

    // Should have used overSlotIndex=12 (09:00), not slotIndexFromClientY(0)=0 (06:00)
    expect(mockPromoteTask).toHaveBeenCalledWith(
      'task-99',
      expect.stringContaining('T09:00'),
      expect.stringContaining('T09:30'),
      'overSlotIndex test',
    )
    wrapper.unmount()
  })

  // ── Structural fix: TaskCards must be transparent to pointer events during drag ──
  it('TaskCard event blocks receive pointer-events-none class while a drag is active', async () => {
    // The structural fix: when dragActive=true, TaskCards have pointer-events-none so
    // drops over event block areas land on the underlying slot div directly, bypassing
    // slotIndexFromClientY and the z-order race that caused slot 0 to always win.
    const { default: DayTimeline } = await import('../DayTimeline.vue')
    const wrapper = mount(DayTimeline, { props: { date: '2024-06-10' }, attachTo: document.body })
    const eventBlock = wrapper.find('[data-event-block]')
    expect(eventBlock.exists()).toBe(true)

    // Before drag: no pointer-events-none
    expect(eventBlock.classes()).not.toContain('pointer-events-none')

    // Simulate drag entering the timed area
    const timedArea = wrapper.find('[data-testid="timed-area"]')
    await timedArea.trigger('dragenter', {
      dataTransfer: { types: ['text/plain'] },
    })
    await wrapper.vm.$nextTick()

    // Should have pointer-events-none during drag
    expect(eventBlock.classes()).toContain('pointer-events-none')

    // After dragleave (leaving the container — relatedTarget null = outside)
    await timedArea.trigger('dragleave', { relatedTarget: null })
    await wrapper.vm.$nextTick()
    expect(eventBlock.classes()).not.toContain('pointer-events-none')

    wrapper.unmount()
  })
})
