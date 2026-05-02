/**
 * TaskCard mode="calendar-event" — CalendarEventBlock absorption (Track 2)
 *
 * Covers the calendar-event mode that replaces CalendarEventBlock.vue.
 *
 * Scenarios:
 *   1. mode="calendar-event" renders at the correct top/height from topPx/heightPx props
 *   2. Renders gcal-badge when event.source !== 'tether'
 *   3. Renders recurring indicator (↻) when is_recurring or is_occurrence
 *   4. Uses resolvedColor prop for background/border; falls back to defaultColor()
 *   5. Has draggable="true" and dragstart payload includes fromStartTime + durationMs
 *   6. Click opens event panel via pushPanel
 *   7. Hides itself (v-show=false) when isDragging is true
 *   8. Does NOT render plan-mode elements (status controls) in calendar-event mode
 */
import { describe, it, expect, vi, beforeEach } from 'vitest'
import { mount } from '@vue/test-utils'
import { createPinia, setActivePinia } from 'pinia'
import type { CalendarEvent } from '../../types/events'
import type { Task } from '../../stores/plan'

// --- Mocks ---

vi.mock('vue-router', () => ({
  useRouter: () => ({ push: vi.fn(), replace: vi.fn(), back: vi.fn() }),
  useRoute: () => ({ path: '/calendar', query: {} }),
  RouterLink: { template: '<a><slot /></a>' },
}))

vi.mock('../../lib/api', () => ({
  api: vi.fn(() => Promise.resolve({ ok: true, json: async () => [] })),
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

vi.mock('../../stores/milestones', () => ({
  useMilestoneStore: () => ({
    all: [],
    taskMilestones: {},
    fetchAll: vi.fn(),
  }),
}))

// --- Fixtures ---

const mockTask: Task = {
  id: 'task-1',
  text: 'Team standup',
  description: null,
  status: 'pending',
  position: 0,
  followup_config: null,
  blocks: [],
  blocked_by: [],
  context_subject: null,
  context_node_id: null,
  anchor_id: null,
  color: null,
  motif: null,
}

const mockEvent: CalendarEvent = {
  id: 'ev-1',
  title: 'Team standup',
  start_time: '2024-06-10T09:00:00',
  end_time: '2024-06-10T09:30:00',   // 30 minutes = 1_800_000 ms
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

const googleEvent: CalendarEvent = {
  ...mockEvent,
  id: 'ev-gcal',
  source: 'google_calendar',
}

const recurringEvent: CalendarEvent = {
  ...mockEvent,
  id: 'ev-recurring',
  is_recurring: true,
}

// --- Tests ---

describe('TaskCard – mode="calendar-event"', () => {
  beforeEach(() => {
    setActivePinia(createPinia())
    mockPushPanel.mockReset()
  })

  it('renders at topPx / heightPx via absolute positioning', async () => {
    const { default: TaskCard } = await import('../TaskCard.vue')
    const wrapper = mount(TaskCard, {
      props: { task: mockTask, mode: 'calendar-event', event: mockEvent, topPx: 120, heightPx: 60 },
    })
    const card = wrapper.find('[data-testid="task-card-calendar-event"]')
    expect(card.exists()).toBe(true)
    const style = card.attributes('style') ?? ''
    expect(style).toContain('top: 120px')
    expect(style).toContain('height: 60px')
  })

  it('renders gcal-badge when event.source is not tether', async () => {
    const { default: TaskCard } = await import('../TaskCard.vue')
    const wrapper = mount(TaskCard, {
      props: { task: mockTask, mode: 'calendar-event', event: googleEvent, heightPx: 60, topPx: 0 },
    })
    expect(wrapper.find('[data-testid="gcal-badge"]').exists()).toBe(true)
  })

  it('renders recurring indicator when is_recurring is true', async () => {
    const { default: TaskCard } = await import('../TaskCard.vue')
    const wrapper = mount(TaskCard, {
      props: { task: mockTask, mode: 'calendar-event', event: recurringEvent, heightPx: 60, topPx: 0 },
    })
    expect(wrapper.find('[data-testid="recurring-indicator"]').exists()).toBe(true)
  })

  it('uses resolvedColor for background and left border; falls back to default #6366f1 for tether events', async () => {
    const { default: TaskCard } = await import('../TaskCard.vue')
    // With explicit resolvedColor
    const wrapper = mount(TaskCard, {
      props: { task: mockTask, mode: 'calendar-event', event: mockEvent, heightPx: 60, topPx: 0, resolvedColor: '#ff0000' },
    })
    const style = wrapper.find('[data-testid="task-card-calendar-event"]').attributes('style') ?? ''
    expect(style).toContain('#ff0000')

    // Without resolvedColor — tether source falls back to #6366f1
    const wrapper2 = mount(TaskCard, {
      props: { task: mockTask, mode: 'calendar-event', event: mockEvent, heightPx: 60, topPx: 0 },
    })
    const style2 = wrapper2.find('[data-testid="task-card-calendar-event"]').attributes('style') ?? ''
    expect(style2).toContain('#6366f1')
  })

  // ── KEY FAILING TEST ── calendarContext not yet wired in TaskCard
  it('dragstart payload includes fromStartTime and durationMs derived from event prop', async () => {
    const { default: TaskCard } = await import('../TaskCard.vue')
    const wrapper = mount(TaskCard, {
      props: { task: mockTask, mode: 'calendar-event', event: mockEvent, heightPx: 60, topPx: 0 },
    })
    const card = wrapper.find('[data-testid="task-card-calendar-event"]')
    expect(card.attributes('draggable')).toBe('true')

    const setDataMock = vi.fn()
    await card.trigger('dragstart', {
      dataTransfer: { setData: setDataMock, effectAllowed: '' },
    })

    expect(setDataMock).toHaveBeenCalledOnce()
    const payload = JSON.parse(setDataMock.mock.calls[0][1] as string)
    expect(payload.type).toBe('task')
    expect(payload.taskId).toBe('task-1')
    // These fields require calendarContext to be wired — will fail until TaskCard is updated
    expect(payload.fromStartTime).toBe('2024-06-10T09:00:00')
    expect(payload.durationMs).toBe(1_800_000)   // 30 min in ms
  })

  it('click opens event panel via pushPanel with task entityId', async () => {
    const { default: TaskCard } = await import('../TaskCard.vue')
    const wrapper = mount(TaskCard, {
      props: { task: mockTask, mode: 'calendar-event', event: mockEvent, heightPx: 60, topPx: 0 },
    })
    await wrapper.find('[data-testid="task-card-calendar-event"]').trigger('click')
    expect(mockPushPanel).toHaveBeenCalledWith({ kind: 'task', entityId: 'task-1' })
  })

  it('is hidden (v-show=false) while drag is active', async () => {
    const { default: TaskCard } = await import('../TaskCard.vue')
    const wrapper = mount(TaskCard, {
      props: { task: mockTask, mode: 'calendar-event', event: mockEvent, heightPx: 60, topPx: 0 },
      attachTo: document.body,
    })
    const card = wrapper.find('[data-testid="task-card-calendar-event"]')
    expect(card.isVisible()).toBe(true)

    await card.trigger('dragstart', {
      dataTransfer: { setData: vi.fn(), effectAllowed: '' },
    })
    // Advance rAF so source-hiding applies
    await new Promise(r => requestAnimationFrame(r))
    await wrapper.vm.$nextTick()
    expect(card.isVisible()).toBe(false)
    wrapper.unmount()
  })

  it('does not render plan-mode status controls in calendar-event mode', async () => {
    const { default: TaskCard } = await import('../TaskCard.vue')
    const wrapper = mount(TaskCard, {
      props: { task: mockTask, mode: 'calendar-event', event: mockEvent, heightPx: 60, topPx: 0 },
    })
    // Plan-mode card should NOT exist; calendar-event card should
    expect(wrapper.find('[data-testid="task-card"]').exists()).toBe(false)
    expect(wrapper.find('[data-testid="task-card-calendar-event"]').exists()).toBe(true)
  })
})
