/**
 * PlanView — DnD bug fixes
 *
 * Bug C: Demoting a calendar event to the anchor column must land in the
 *        TARGETED anchor, not always the first one.
 *
 * Previously the whole anchor column was a single drop zone; the anchorId was
 * derived from ev.anchor_id ?? anchors[0].id, which always picks the first
 * anchor when the event has no stored anchor_id.
 *
 * Fix: each AnchorBlock wrapper gets its own @drop="(e) => onAnchorDrop(e, anchor.id)"
 * so the correct anchor is always passed.
 */
import { describe, it, expect, vi, beforeEach } from 'vitest'
import { mount, flushPromises } from '@vue/test-utils'
import { createPinia, setActivePinia } from 'pinia'
import { defineComponent, h } from 'vue'

vi.mock('vue-router', () => ({
  useRouter: () => ({ push: vi.fn(), replace: vi.fn() }),
  useRoute: () => ({
    params: { view: 'day', date: '2024-06-10' },
    path: '/plan/day/2024-06-10',
    query: {},
  }),
  RouterLink: defineComponent({
    props: ['to'],
    setup(_p, { slots }) { return () => h('a', {}, slots.default?.()) },
  }),
  RouterView: defineComponent({ template: '<div />' }),
}))

vi.mock('../../lib/api', () => ({
  api: vi.fn(() => Promise.resolve({ ok: true, json: async () => ({}) })),
}))

const mockDemoteEvent = vi.fn()
const mockFetchPlan = vi.fn()

vi.mock('../../stores/events', () => ({
  useEventStore: () => ({
    events: [
      {
        id: 'ev-1',
        title: 'Meeting',
        task_id: 'task-1',
        start_time: '2024-06-10T09:00:00',
        end_time: '2024-06-10T09:30:00',
        source: 'tether',
        external_id: null,
        anchor_id: null,  // null → previously always fell back to anchors[0]
        color: null,
        is_recurring: false,
        is_occurrence: false,
        rrule: null,
        is_all_day: false,
        context_subject: null,
      },
    ],
    fetchEvents: vi.fn(),
    demoteEvent: mockDemoteEvent,
    promoteTask: vi.fn(),
    moveEvent: vi.fn(),
    createTaskAndPromote: vi.fn(),
    deleteEvent: vi.fn(),
    removeEventsForTask: vi.fn(),
  }),
}))

vi.mock('../../stores/anchors', () => ({
  useAnchorStore: () => ({
    anchors: [
      { id: 'anchor-morning', name: 'Morning', time: '08:00', color: '#3b82f6', motif: null, duration_minutes: 240 },
      { id: 'anchor-afternoon', name: 'Afternoon', time: '13:00', color: '#f59e0b', motif: null, duration_minutes: 240 },
    ],
    fetchAnchors: vi.fn(),
  }),
  computeAnchorStates: vi.fn(() => new Map()),
}))

vi.mock('../../stores/plan', () => ({
  usePlanStore: () => ({
    plan: { date: '2024-06-10', anchors: {}, acknowledgements: {}, check_in_log: [] },
    loading: false,
    today: '2024-06-10',
    fetchPlan: mockFetchPlan,
    plans: {},
    activeDate: '2024-06-10',
  }),
}))

vi.mock('../../stores/milestones', () => ({
  useMilestoneStore: () => ({ all: [], fetchAll: vi.fn(), taskMilestones: {} }),
}))

vi.mock('../../composables/useSlideOver', () => ({
  useSlideOver: () => ({
    push: vi.fn(),
    pop: vi.fn(),
    stack: { value: [] },
    close: vi.fn(),
    restoreFromUrl: vi.fn(),
  }),
}))

/**
 * Bug B: PlanView outer anchor wrapper must not swallow task→task drops.
 *
 * The outer `data-anchor-drop-zone` div carries @drop="onAnchorDrop". That handler
 * only acts when the payload has `fromStartTime` (calendar event demotion). When a
 * plain task is dropped (no fromStartTime), the outer handler must return early so
 * AnchorBlock's internal useDropZone can process the move. Regression: if
 * onAnchorDrop were ever changed to call preventDefault/stopPropagation
 * unconditionally, task→task inter-anchor moves would be silently swallowed.
 */
describe('PlanView — Bug B: outer wrapper ignores plain task drops (no fromStartTime)', () => {
  beforeEach(() => {
    setActivePinia(createPinia())
    mockDemoteEvent.mockReset()
    mockFetchPlan.mockReset()
  })

  it('dropping a plain task (no fromStartTime) onto anchor zone does NOT call demoteEvent', async () => {
    const { default: PlanView } = await import('../PlanView.vue')
    const wrapper = mount(PlanView, { props: { view: 'day', date: '2024-06-10' } })
    await flushPromises()
    // fetchPlan is called once on mount (watch immediate) — reset before drop so we
    // only assert on what the drop handler itself triggers.
    mockFetchPlan.mockReset()
    mockDemoteEvent.mockReset()

    const dropZones = wrapper.findAll('[data-anchor-drop-zone]')
    expect(dropZones.length).toBe(2)

    // Plain task payload — NO fromStartTime
    const payload = {
      type: 'task',
      taskId: 'task-99',
      title: 'Regular task',
      fromAnchorId: 'anchor-morning',
      fromDate: '2024-06-10',
    }
    await dropZones[1].trigger('drop', {
      dataTransfer: {
        getData: (t: string) => t === 'text/plain' ? JSON.stringify(payload) : '',
      },
    })
    await flushPromises()

    // demoteEvent must NOT be called for regular task moves
    expect(mockDemoteEvent).not.toHaveBeenCalled()
    // fetchPlan must NOT be triggered by the outer handler for non-demotion drops
    expect(mockFetchPlan).not.toHaveBeenCalled()
  })
})

describe('PlanView — Bug C: per-anchor demotion drop', () => {
  beforeEach(() => {
    setActivePinia(createPinia())
    mockDemoteEvent.mockReset()
    mockFetchPlan.mockReset()
  })

  it('renders one drop zone per anchor (not a single column drop zone)', async () => {
    const { default: PlanView } = await import('../PlanView.vue')
    const wrapper = mount(PlanView, { props: { view: 'day', date: '2024-06-10' } })
    await flushPromises()
    const dropZones = wrapper.findAll('[data-anchor-drop-zone]')
    expect(dropZones.length).toBe(2)
  })

  it('dropping a calendar event onto the second anchor calls demoteEvent with that anchor id', async () => {
    const { default: PlanView } = await import('../PlanView.vue')
    const wrapper = mount(PlanView, { props: { view: 'day', date: '2024-06-10' } })
    await flushPromises()

    const dropZones = wrapper.findAll('[data-anchor-drop-zone]')
    expect(dropZones.length).toBe(2)
    const afternoonZone = dropZones[1]  // anchor-afternoon

    const payload = {
      type: 'task',
      taskId: 'task-1',
      fromStartTime: '2024-06-10T09:00:00',
    }
    await afternoonZone.trigger('drop', {
      dataTransfer: {
        getData: (t: string) => t === 'text/plain' ? JSON.stringify(payload) : '',
      },
    })
    await flushPromises()

    // Must target anchor-afternoon specifically, not anchor-morning (the first one)
    expect(mockDemoteEvent).toHaveBeenCalledWith('ev-1', 'anchor-afternoon', '2024-06-10')
    expect(mockDemoteEvent).not.toHaveBeenCalledWith('ev-1', 'anchor-morning', expect.any(String))
  })
})
