/**
 * CalendarView — HTML5 DnD refactor (Track 2)
 *
 * Tests for the replacement of the mouse-event drag system with HTML5 DnD.
 *
 * Key failing tests (before refactor):
 *   - Event blocks render as TaskCard, not CalendarEventBlock
 *   - Dropping a calendar-event payload calls eventStore.moveEvent
 *   - Source event block hides via v-show during HTML5 drag
 *
 * Regression tests (must keep passing):
 *   - Drag-to-create via mousedown still works
 *   - Click on event block still opens panel
 */
import { describe, it, expect, vi, beforeEach } from 'vitest'
import { mount, flushPromises } from '@vue/test-utils'
import { createPinia, setActivePinia } from 'pinia'
import { defineComponent, h, nextTick } from 'vue'
import { resetFocusedDay } from '../../composables/useCalendarFocus'
import type { CalendarEvent } from '../../types/events'

// --- Mocks ---

vi.mock('vue-router', () => ({
  useRouter: () => ({ push: vi.fn(), replace: vi.fn(), back: vi.fn() }),
  useRoute: () => ({ path: '/calendar', query: {} }),
  RouterLink: defineComponent({
    props: ['to'],
    setup(props, { slots }) {
      return () => h('a', { href: typeof props.to === 'string' ? props.to : '#' }, slots.default?.())
    },
  }),
  RouterView: defineComponent({ template: '<div />' }),
}))

vi.mock('../../lib/api', () => ({
  api: vi.fn(() => Promise.resolve({ ok: true, json: async () => [] })),
}))

// Compute today's date string the same way CalendarView does
const d = new Date()
const todayStr = `${d.getFullYear()}-${String(d.getMonth() + 1).padStart(2, '0')}-${String(d.getDate()).padStart(2, '0')}`

const mockTimedEvent: CalendarEvent = {
  id: 'ev-today',
  title: 'Team meeting',
  start_time: `${todayStr}T10:00:00`,
  end_time: `${todayStr}T10:30:00`,
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

const mockMoveEvent = vi.fn()
const mockPromoteTask = vi.fn()
const mockCreateTaskAndPromote = vi.fn(() => Promise.resolve('new-task-id'))

vi.mock('../../stores/events', () => ({
  useEventStore: () => ({
    events: [mockTimedEvent],
    loading: false,
    fetchEvents: vi.fn(),
    moveEvent: mockMoveEvent,
    promoteTask: mockPromoteTask,
    demoteEvent: vi.fn(),
    createTaskAndPromote: mockCreateTaskAndPromote,
    deleteEvent: vi.fn(),
  }),
}))

vi.mock('../../stores/anchors', () => ({
  useAnchorStore: () => ({
    anchors: [],
    fetchAnchors: vi.fn(),
  }),
}))

vi.mock('../../stores/plan', () => ({
  usePlanStore: () => ({
    plan: null,
    plans: {},
    fetchPlan: vi.fn(),
    fetchPlanRange: vi.fn(),
  }),
}))

vi.mock('../../stores/milestones', () => ({
  useMilestoneStore: () => ({
    all: [],
    fetchAll: vi.fn(),
  }),
}))

vi.mock('../../stores/kanban', () => ({
  useKanbanStore: () => ({
    columns: [],
    fetchColumns: vi.fn(),
  }),
}))

vi.mock('../../stores/context', () => ({
  useContextStore: () => ({
    nodes: {},
    rootNodes: [],
    childrenOf: vi.fn(() => []),
    fetchRootNodes: vi.fn(() => Promise.resolve()),
    fetchChildren: vi.fn(),
  }),
}))

const mockPushPanel = vi.fn()
vi.mock('../../composables/useSlideOver', () => ({
  useSlideOver: () => ({
    stack: { value: [] },
    push: mockPushPanel,
    pop: vi.fn(),
    close: vi.fn(),
    restoreFromUrl: vi.fn(),
  }),
}))

// --- Tests ---

describe('CalendarView – HTML5 DnD refactor', () => {
  beforeEach(() => {
    setActivePinia(createPinia())
    resetFocusedDay()
    mockMoveEvent.mockReset()
    mockPromoteTask.mockReset()
    mockPushPanel.mockReset()
    mockCreateTaskAndPromote.mockReset()
    mockCreateTaskAndPromote.mockResolvedValue('new-task-id')
  })

  // ── KEY FAILING TEST #1 ────────────────────────────────────────────────────
  // CalendarView currently uses <CalendarEventBlock>; after refactor it uses
  // <TaskCard mode="calendar-event"> which renders data-testid="task-card-calendar-event"
  it('event blocks render as TaskCard with mode="calendar-event" instead of CalendarEventBlock', async () => {
    const { default: CalendarView } = await import('../CalendarView.vue')
    const wrapper = mount(CalendarView)
    await flushPromises()
    await nextTick()
    // After refactor: TaskCard calendar-event renders for mockTimedEvent
    expect(wrapper.find('[data-testid="task-card-calendar-event"]').exists()).toBe(true)
  })

  // ── KEY FAILING TEST #2 ────────────────────────────────────────────────────
  // Current CalendarView only handles task promotions in onDrop; calendar-event
  // payloads (type:'calendar-event') are ignored. After refactor, handleColumnDrop
  // routes these to eventStore.moveEvent with preserved duration.
  it('dropping a calendar-event payload onto a day column calls eventStore.moveEvent with preserved duration', async () => {
    const { default: CalendarView } = await import('../CalendarView.vue')
    const wrapper = mount(CalendarView)
    await flushPromises()

    const todayCol = wrapper.find(`[data-testid="day-col-${todayStr}"]`)
    expect(todayCol.exists()).toBe(true)

    const durationMs = 30 * 60_000  // 30 min
    const payload = {
      type: 'calendar-event',
      eventId: 'ev-today',
      title: 'Team meeting',
      fromStartTime: `${todayStr}T10:00:00`,
      durationMs,
    }
    await todayCol.trigger('drop', {
      dataTransfer: {
        getData: (type: string) => type === 'text/plain' ? JSON.stringify(payload) : '',
      },
    })

    expect(mockMoveEvent).toHaveBeenCalled()
    const [id, newStart, newEnd] = mockMoveEvent.mock.calls[0]
    expect(id).toBe('ev-today')
    // New end should be 30 minutes after new start
    const startMs = new Date(newStart as string).getTime()
    const endMs = new Date(newEnd as string).getTime()
    expect(endMs - startMs).toBe(durationMs)
  })

  // ── KEY FAILING TEST #3 ────────────────────────────────────────────────────
  // CalendarEventBlock has no draggable attr / HTML5 drag; after refactor TaskCard
  // has draggable="true" and v-show="!isDragging" — source block hides on pickup.
  it('source event block is hidden (v-show=false) while HTML5 drag is active', async () => {
    const { default: CalendarView } = await import('../CalendarView.vue')
    const wrapper = mount(CalendarView, { attachTo: document.body })
    await flushPromises()
    await nextTick()

    const eventBlock = wrapper.find('[data-testid="task-card-calendar-event"]')
    expect(eventBlock.exists()).toBe(true)
    expect(eventBlock.isVisible()).toBe(true)

    await eventBlock.trigger('dragstart', {
      dataTransfer: { setData: vi.fn(), effectAllowed: '' },
    })
    // Advance rAF so source-hiding applies
    await new Promise(r => requestAnimationFrame(r))
    await nextTick()

    expect(eventBlock.isVisible()).toBe(false)
    wrapper.unmount()
  })

  // ── REGRESSION: task drop from sidebar still promotes to event ─────────────
  it('dropping a task payload (sidebar drag) onto a day column promotes it to an event', async () => {
    const { default: CalendarView } = await import('../CalendarView.vue')
    const wrapper = mount(CalendarView)
    await flushPromises()

    const todayCol = wrapper.find(`[data-testid="day-col-${todayStr}"]`)
    expect(todayCol.exists()).toBe(true)

    // Drop a task that has NO existing event (task-99 is not in mockTimedEvent.task_id)
    const payload = { type: 'task', taskId: 'task-99', title: 'New task from sidebar' }
    await todayCol.trigger('drop', {
      dataTransfer: {
        getData: (type: string) => type === 'text/plain' ? JSON.stringify(payload) : '',
      },
    })

    expect(mockPromoteTask).toHaveBeenCalledWith(
      'task-99',
      expect.any(String),
      expect.any(String),
      'New task from sidebar',
    )
  })

  // ── REGRESSION: drag-to-create via mousedown still works ──────────────────
  it('mousedown on empty column area initiates drag-to-create', async () => {
    const { default: CalendarView } = await import('../CalendarView.vue')
    const wrapper = mount(CalendarView)
    await flushPromises()

    const todayCol = wrapper.find(`[data-testid="day-col-${todayStr}"]`)
    expect(todayCol.exists()).toBe(true)

    // Mousedown on column element starts create state (onDayColumnMousedown)
    await todayCol.trigger('mousedown', { clientY: 200 })
    // onWindowMousemove is a WINDOW listener — must dispatch on window to update currentY
    window.dispatchEvent(new MouseEvent('mousemove', { clientY: 260, bubbles: true }))
    await nextTick()
    // onWindowMouseup fires; heightY = 260-200 = 60px > MIN_HEIGHT (15px) → creates event
    window.dispatchEvent(new MouseEvent('mouseup', { clientY: 260, bubbles: true }))
    await flushPromises()

    expect(mockCreateTaskAndPromote).toHaveBeenCalled()
  })

  // ── REGRESSION: click on event block opens panel ───────────────────────────
  it('click on event block opens the task detail panel', async () => {
    const { default: CalendarView } = await import('../CalendarView.vue')
    const wrapper = mount(CalendarView)
    await flushPromises()
    await nextTick()

    const eventBlock = wrapper.find('[data-testid="task-card-calendar-event"]')
    expect(eventBlock.exists()).toBe(true)
    await eventBlock.trigger('click')

    expect(mockPushPanel).toHaveBeenCalledWith({ kind: 'task', entityId: 'task-1' })
  })
})
