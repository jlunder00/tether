/**
 * PlanView — MiniCalendar dropdown/popover integration
 * A calendar icon button near the D/W/M tabs toggles the MiniCalendar.
 * Clicking a day navigates to that date in the current view.
 */
import { describe, it, expect, vi, beforeEach } from 'vitest'
import { mount } from '@vue/test-utils'
import { createPinia, setActivePinia } from 'pinia'

const mockPush = vi.fn()

vi.mock('vue-router', () => ({
  useRouter: () => ({ push: mockPush }),
  useRoute: () => ({ path: '/plan/day/2026-05-15' }),
  RouterLink: { template: '<a><slot /></a>', props: ['to'] },
}))

vi.mock('../../lib/api', () => ({
  api: vi.fn(() => Promise.resolve({ ok: true, json: async () => [] })),
}))

// Stub heavy child components
vi.mock('../../components/AnchorBlock.vue', () => ({
  default: { template: '<div data-testid="anchor-block" />' },
}))
vi.mock('../../components/plan/PlanWeekView.vue', () => ({
  default: { template: '<div data-testid="plan-week-view" />' },
}))
vi.mock('../../components/MonthView.vue', () => ({
  default: { template: '<div data-testid="month-view" />' },
}))
vi.mock('../../components/DayTimeline.vue', () => ({
  default: { template: '<div data-testid="day-timeline" />', props: ['date'], emits: ['create-at', 'open-event'] },
}))
vi.mock('../../components/plan/MiniCalendar.vue', () => ({
  default: {
    template: '<div data-testid="mini-calendar" />',
    emits: ['day-click'],
  },
}))

describe('PlanView — MiniCalendar popover', () => {
  beforeEach(() => {
    setActivePinia(createPinia())
    vi.clearAllMocks()
  })

  async function mountView(view = 'day', date = '2026-05-15') {
    const { default: PlanView } = await import('../PlanView.vue')
    return mount(PlanView, {
      props: { view, date },
      global: { stubs: { RouterLink: { template: '<a><slot /></a>', props: ['to'] } } },
    })
  }

  it('renders a mini-calendar toggle button near the view tabs', async () => {
    const w = await mountView()
    expect(w.find('[data-testid="mini-cal-toggle"]').exists()).toBe(true)
  })

  it('MiniCalendar is hidden by default', async () => {
    const w = await mountView()
    expect(w.find('[data-testid="mini-calendar"]').exists()).toBe(false)
  })

  it('clicking the toggle button shows the MiniCalendar', async () => {
    const w = await mountView()
    await w.find('[data-testid="mini-cal-toggle"]').trigger('click')
    expect(w.find('[data-testid="mini-calendar"]').exists()).toBe(true)
  })

  it('clicking the toggle button again hides the MiniCalendar', async () => {
    const w = await mountView()
    await w.find('[data-testid="mini-cal-toggle"]').trigger('click')
    await w.find('[data-testid="mini-cal-toggle"]').trigger('click')
    expect(w.find('[data-testid="mini-calendar"]').exists()).toBe(false)
  })

  it('day-click from MiniCalendar navigates to that date in the current view', async () => {
    const w = await mountView('day', '2026-05-15')
    await w.find('[data-testid="mini-cal-toggle"]').trigger('click')

    const { default: MiniCalendarStub } = await import('../../components/plan/MiniCalendar.vue')
    const cal = w.findComponent(MiniCalendarStub)
    await cal.vm.$emit('day-click', '2026-06-03')
    await w.vm.$nextTick()

    expect(mockPush).toHaveBeenCalledWith('/plan/day/2026-06-03')
  })

  it('day-click in week view navigates to the week route', async () => {
    const w = await mountView('week', '2026-05-15')
    await w.find('[data-testid="mini-cal-toggle"]').trigger('click')

    const { default: MiniCalendarStub } = await import('../../components/plan/MiniCalendar.vue')
    const cal = w.findComponent(MiniCalendarStub)
    await cal.vm.$emit('day-click', '2026-06-03')
    await w.vm.$nextTick()

    expect(mockPush).toHaveBeenCalledWith('/plan/week/2026-06-03')
  })

  it('day-click closes the popover after navigating', async () => {
    const w = await mountView('day', '2026-05-15')
    await w.find('[data-testid="mini-cal-toggle"]').trigger('click')
    expect(w.find('[data-testid="mini-calendar"]').exists()).toBe(true)

    const { default: MiniCalendarStub } = await import('../../components/plan/MiniCalendar.vue')
    const cal = w.findComponent(MiniCalendarStub)
    await cal.vm.$emit('day-click', '2026-06-03')
    await w.vm.$nextTick()

    expect(w.find('[data-testid="mini-calendar"]').exists()).toBe(false)
  })

  it('MiniCalendar is shown in week view too', async () => {
    const w = await mountView('week')
    await w.find('[data-testid="mini-cal-toggle"]').trigger('click')
    expect(w.find('[data-testid="mini-calendar"]').exists()).toBe(true)
  })
})
