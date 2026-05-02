/**
 * MiniCalendar — compact month navigation popover
 * Clicking a day emits 'day-click' up to PlanView for navigation.
 * No drag-and-drop — MiniCalendar is navigation-only.
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
    emits: ['day-click'],
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

describe('MiniCalendar — day-click navigation', () => {
  beforeEach(() => {
    setActivePinia(createPinia())
    vi.clearAllMocks()
  })

  async function mountCalendar() {
    const { default: MiniCalendar } = await import('../MiniCalendar.vue')
    return mount(MiniCalendar, {})
  }

  it('emits day-click with the date when a day cell emits day-click', async () => {
    const w = await mountCalendar()
    const { default: MiniCalendarDayStub } = await import('../MiniCalendarDay.vue')
    const dayWrappers = w.findAllComponents(MiniCalendarDayStub)
    expect(dayWrappers).toHaveLength(42)

    const targetWrapper = dayWrappers[10]
    const targetDate = targetWrapper.props('date') as string

    await targetWrapper.vm.$emit('day-click', targetDate)
    await w.vm.$nextTick()

    expect(w.emitted('day-click')).toBeTruthy()
    expect(w.emitted('day-click')![0][0]).toBe(targetDate)
  })
})
