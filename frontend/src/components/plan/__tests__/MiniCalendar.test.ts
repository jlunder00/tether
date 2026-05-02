/**
 * MiniCalendar — compact month sidebar for plan view
 * Day cells are drop targets via MiniCalendarDay child component (one useDropZone per cell).
 */
import { describe, it, expect, vi, beforeEach } from 'vitest'
import { mount } from '@vue/test-utils'
import { createPinia, setActivePinia } from 'pinia'

vi.mock('vue-router', () => ({
  useRouter: () => ({ push: vi.fn() }),
  useRoute: () => ({ path: '/' }),
}))

vi.mock('../../../lib/api', () => ({
  api: vi.fn(() => Promise.resolve({ ok: true, json: async () => [] })),
}))

// Stub MiniCalendarDay to isolate MiniCalendar rendering
vi.mock('../MiniCalendarDay.vue', () => ({
  default: {
    props: ['date', 'taskCount', 'isToday'],
    template: '<div :data-testid="\'day-\' + date" :data-date="date" />',
    emits: ['task-dropped'],
  },
}))

describe('MiniCalendar — rendering', () => {
  beforeEach(() => {
    setActivePinia(createPinia())
    vi.clearAllMocks()
  })

  async function mountCalendar() {
    const { default: MiniCalendar } = await import('../MiniCalendar.vue')
    return mount(MiniCalendar, {})
  }

  it('renders 42 day cells (6 weeks × 7)', async () => {
    const w = await mountCalendar()
    const days = w.findAll('[data-date]')
    expect(days).toHaveLength(42)
  })

  it('renders prev/next navigation buttons', async () => {
    const w = await mountCalendar()
    expect(w.find('[data-testid="mini-cal-prev"]').exists()).toBe(true)
    expect(w.find('[data-testid="mini-cal-next"]').exists()).toBe(true)
  })

  it('advancing to next month changes the displayed day cells', async () => {
    const w = await mountCalendar()
    const initialFirst = w.findAll('[data-date]')[0].attributes('data-date')
    await w.find('[data-testid="mini-cal-next"]').trigger('click')
    const nextFirst = w.findAll('[data-date]')[0].attributes('data-date')
    expect(nextFirst).not.toBe(initialFirst)
  })
})

describe('MiniCalendar — drop delegation', () => {
  beforeEach(() => {
    setActivePinia(createPinia())
    vi.clearAllMocks()
  })

  async function mountCalendar() {
    const { default: MiniCalendar } = await import('../MiniCalendar.vue')
    return mount(MiniCalendar, {})
  }

  it('calls planStore.moveTaskToAnchor when a task-dropped event is emitted from a day cell', async () => {
    const { usePlanStore } = await import('../../../stores/plan')
    const store = usePlanStore()
    const spy = vi.spyOn(store, 'moveTaskToAnchor').mockResolvedValue(undefined)

    const w = await mountCalendar()

    // Use findAllComponents to get Vue component wrappers (not DOM wrappers).
    // trigger('task-dropped') fires a native DOM event — Vue's @task-dropped listener
    // only fires when the child component calls emit(). We need vm.$emit() here.
    const { default: MiniCalendarDayStub } = await import('../MiniCalendarDay.vue')
    const dayWrappers = w.findAllComponents(MiniCalendarDayStub)
    expect(dayWrappers).toHaveLength(42)

    const targetWrapper = dayWrappers[10]
    const targetDate = targetWrapper.props('date') as string

    // Emit via Vue's component emit — propagates to parent's @task-dropped listener
    await targetWrapper.vm.$emit('task-dropped', { taskId: 'task-xyz', date: targetDate, fromAnchorId: 'morning' })
    await w.vm.$nextTick()

    // MiniCalendar handles the event and calls the store
    expect(spy).toHaveBeenCalledOnce()
    const call = spy.mock.calls[0][0]
    expect(call.taskId).toBe('task-xyz')
    expect(call.newDate).toBe(targetDate)
  })
})
