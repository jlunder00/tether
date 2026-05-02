/**
 * MiniCalendarDay — individual day cell for navigation
 * Clicking a cell emits 'day-click' with the date string.
 * No drop-target behavior — MiniCalendar is navigation-only.
 */
import { describe, it, expect, vi, beforeEach } from 'vitest'
import { mount } from '@vue/test-utils'
import { createPinia, setActivePinia } from 'pinia'

vi.mock('../../../lib/api', () => ({
  api: vi.fn(() => Promise.resolve({ ok: true, json: async () => [] })),
}))

describe('MiniCalendarDay — navigation', () => {
  beforeEach(() => {
    setActivePinia(createPinia())
    vi.clearAllMocks()
  })

  async function mountDay(props: Record<string, unknown> = {}) {
    const { default: MiniCalendarDay } = await import('../MiniCalendarDay.vue')
    return mount(MiniCalendarDay, {
      props: {
        date: '2026-05-15',
        taskCount: 0,
        isToday: false,
        ...props,
      },
    })
  }

  it('renders a day cell with the correct date', async () => {
    const w = await mountDay()
    expect(w.find('[data-date="2026-05-15"]').exists()).toBe(true)
  })

  it('emits day-click with the date when the cell is clicked', async () => {
    const w = await mountDay({ date: '2026-06-10' })
    await w.find('[data-date="2026-06-10"]').trigger('click')
    expect(w.emitted('day-click')).toBeTruthy()
    expect(w.emitted('day-click')![0][0]).toBe('2026-06-10')
  })

  it('highlights today cell with today styling', async () => {
    const w = await mountDay({ isToday: true })
    const daySpan = w.find('[data-date="2026-05-15"] span')
    expect(daySpan.classes()).toContain('text-[--accent]')
  })

  it('shows task count when taskCount > 0', async () => {
    const w = await mountDay({ taskCount: 3 })
    expect(w.text()).toContain('3')
  })
})
