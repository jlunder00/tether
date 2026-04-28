import { describe, it, expect, vi, beforeEach } from 'vitest'
import { mount, flushPromises } from '@vue/test-utils'
import { createPinia, setActivePinia } from 'pinia'
import { nextTick } from 'vue'

vi.mock('vue-router', () => ({
  useRouter: () => ({ push: vi.fn() }),
  useRoute: () => ({ path: '/dashboard' }),
}))

vi.mock('../../lib/api', () => ({
  api: vi.fn(() => Promise.resolve({ ok: true, json: async () => [] })),
}))

describe('DashboardView', () => {
  beforeEach(() => {
    setActivePinia(createPinia())
    vi.clearAllMocks()
  })

  it('renders the Dashboard heading', async () => {
    const { default: DashboardView } = await import('../DashboardView.vue')
    const wrapper = mount(DashboardView)
    expect(wrapper.text()).toContain('Dashboard')
  })

  it('shows all-day event chip when eventStore has is_all_day event for today', async () => {
    const { useEventStore } = await import('../../stores/events')
    const { default: DashboardView } = await import('../DashboardView.vue')
    const wrapper = mount(DashboardView)
    await flushPromises()

    const d = new Date()
    const TODAY = `${d.getFullYear()}-${String(d.getMonth() + 1).padStart(2, '0')}-${String(d.getDate()).padStart(2, '0')}`

    const eventStore = useEventStore()
    eventStore.events.push({
      id: 'ev-allday-1',
      title: 'Company Holiday',
      start_time: `${TODAY}T00:00:00`,
      end_time: `${TODAY}T23:59:59`,
      source: 'tether',
      external_id: null,
      task_id: null,
      anchor_id: null,
      color: '#e74c3c',
      is_recurring: false,
      is_occurrence: false,
      is_all_day: true,
      rrule: null,
      context_subject: null,
    })
    await nextTick()

    const chip = wrapper.find('[data-testid="all-day-event-chip"]')
    expect(chip.exists()).toBe(true)
    expect(chip.text()).toContain('Company Holiday')
  })

  it('does not show all-day chip for timed (non-all-day) events', async () => {
    const { useEventStore } = await import('../../stores/events')
    const { default: DashboardView } = await import('../DashboardView.vue')
    const wrapper = mount(DashboardView)
    await flushPromises()

    const d = new Date()
    const TODAY = `${d.getFullYear()}-${String(d.getMonth() + 1).padStart(2, '0')}-${String(d.getDate()).padStart(2, '0')}`

    const eventStore = useEventStore()
    eventStore.events.push({
      id: 'ev-timed-1',
      title: 'Timed Meeting',
      start_time: `${TODAY}T09:00:00`,
      end_time: `${TODAY}T10:00:00`,
      source: 'tether',
      external_id: null,
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

    const chip = wrapper.find('[data-testid="all-day-event-chip"]')
    expect(chip.exists()).toBe(false)
  })
})
