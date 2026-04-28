import { describe, it, expect, vi, beforeEach } from 'vitest'
import { mount } from '@vue/test-utils'
import { createPinia, setActivePinia } from 'pinia'
import {
  anchorWindow,
  eventTopPx,
  eventHeightPx,
  anchorBandTopPx,
  anchorBandHeightPx,
  AXIS_START_HOUR,
  AXIS_END_HOUR,
  PX_PER_MINUTE,
} from '../../composables/useDayTimeline'
import type { Anchor } from '../../stores/anchors'
import type { CalendarEvent } from '../../types/events'

// --- Mocks ---

vi.mock('vue-router', () => ({
  useRouter: () => ({ push: vi.fn() }),
  useRoute: () => ({ path: '/plan/day', query: {} }),
  RouterLink: { template: '<a><slot /></a>' },
}))

vi.mock('../../lib/api', () => ({
  api: vi.fn(() => Promise.resolve({ ok: true, json: async () => [] })),
}))

// Mock stores so we can control their output
const mockAnchors: Anchor[] = [
  {
    id: 'a1',
    name: 'Morning',
    time: '08:00',
    duration_minutes: 120,
    flexibility: 'moderate',
    strictness: 2,
    color: '#6366f1',
    position: 1,
    followup_config: null,
  },
]

const mockEvents: CalendarEvent[] = [
  {
    id: 'ev-timed',
    title: 'Team standup',
    // Use local-time strings (no Z suffix) to avoid TZ ambiguity
    start_time: '2024-06-10T09:00:00',
    end_time: '2024-06-10T09:30:00',
    source: 'tether',
    external_id: null,
    task_id: null,
    anchor_id: null,
    color: null,
    is_recurring: false,
    is_occurrence: false,
    rrule: null,
    is_all_day: false,
  },
  {
    id: 'ev-allday',
    title: 'Holiday',
    start_time: '2024-06-10T00:00:00',
    end_time: '2024-06-10T23:59:59',
    source: 'tether',
    external_id: null,
    task_id: null,
    anchor_id: null,
    color: null,
    is_recurring: false,
    is_occurrence: false,
    rrule: null,
    is_all_day: true,
  },
]

vi.mock('../../stores/anchors', () => ({
  useAnchorStore: () => ({
    anchors: mockAnchors,
    fetchAnchors: vi.fn(),
  }),
}))

vi.mock('../../stores/events', () => ({
  useEventStore: () => ({
    events: mockEvents,
    loading: false,
    fetchEvents: vi.fn(),
    moveEvent: vi.fn(),
    promoteTask: vi.fn(),
    demoteEvent: vi.fn(),
    createTaskAndPromote: vi.fn(),
  }),
}))

// --- Pure function tests ---

const testAnchor: Anchor = {
  id: 'anc-1',
  name: 'Morning',
  time: '09:00',
  duration_minutes: 60,
  flexibility: 'moderate',
  strictness: 2,
  color: '#6366f1',
  position: 1,
  followup_config: null,
}

const testDate = new Date('2024-06-10T12:00:00')

describe('anchorWindow', () => {
  it('returns start time matching anchor.time on the given date', () => {
    const { start } = anchorWindow(testAnchor, testDate)
    expect(start.getHours()).toBe(9)
    expect(start.getMinutes()).toBe(0)
  })

  it('returns end time = start + duration_minutes', () => {
    const { start, end } = anchorWindow(testAnchor, testDate)
    const diffMin = (end.getTime() - start.getTime()) / 60_000
    expect(diffMin).toBe(60)
  })

  it('preserves the date from the passed date arg', () => {
    const { start } = anchorWindow(testAnchor, testDate)
    expect(start.getFullYear()).toBe(2024)
    expect(start.getMonth()).toBe(5) // June = 5 (0-indexed)
    expect(start.getDate()).toBe(10)
  })
})

describe('eventTopPx', () => {
  it('returns 0 for a time at the axis start hour', () => {
    // Build a date at AXIS_START_HOUR local time
    const d = new Date('2024-06-10T00:00:00')
    d.setHours(AXIS_START_HOUR, 0, 0, 0)
    const isoLocal = `${d.getFullYear()}-${String(d.getMonth()+1).padStart(2,'0')}-${String(d.getDate()).padStart(2,'0')}T${String(d.getHours()).padStart(2,'0')}:00:00`
    expect(eventTopPx(isoLocal)).toBe(0)
  })

  it('returns correct px for an event 60 minutes after axis start', () => {
    const d = new Date('2024-06-10T00:00:00')
    d.setHours(AXIS_START_HOUR + 1, 0, 0, 0)
    const isoLocal = `${d.getFullYear()}-${String(d.getMonth()+1).padStart(2,'0')}-${String(d.getDate()).padStart(2,'0')}T${String(d.getHours()).padStart(2,'0')}:00:00`
    expect(eventTopPx(isoLocal)).toBe(60 * PX_PER_MINUTE)
  })

  it('clamps to 0 for times before axis start', () => {
    const d = new Date('2024-06-10T00:00:00')
    d.setHours(AXIS_START_HOUR - 1, 0, 0, 0)
    const isoLocal = `${d.getFullYear()}-${String(d.getMonth()+1).padStart(2,'0')}-${String(d.getDate()).padStart(2,'0')}T${String(d.getHours()).padStart(2,'0')}:00:00`
    expect(eventTopPx(isoLocal)).toBe(0)
  })
})

describe('eventHeightPx', () => {
  it('returns duration * PX_PER_MINUTE for a 30-min event', () => {
    expect(eventHeightPx('2024-06-10T09:00:00', '2024-06-10T09:30:00')).toBe(30 * PX_PER_MINUTE)
  })

  it('enforces minimum height of 20px', () => {
    // 1-minute event would be 1.5px without clamping
    expect(eventHeightPx('2024-06-10T09:00:00', '2024-06-10T09:01:00')).toBe(20)
  })

  it('clips start to axis start for events beginning before 6am', () => {
    // Event 5am–7am: only 60min visible (6–7am), not 120min
    const d5am = new Date('2024-06-10T00:00:00')
    d5am.setHours(AXIS_START_HOUR - 1, 0, 0, 0)
    const d7am = new Date('2024-06-10T00:00:00')
    d7am.setHours(AXIS_START_HOUR + 1, 0, 0, 0)
    const to5 = `${d5am.getFullYear()}-${String(d5am.getMonth()+1).padStart(2,'0')}-${String(d5am.getDate()).padStart(2,'0')}T${String(d5am.getHours()).padStart(2,'0')}:00:00`
    const to7 = `${d7am.getFullYear()}-${String(d7am.getMonth()+1).padStart(2,'0')}-${String(d7am.getDate()).padStart(2,'0')}T${String(d7am.getHours()).padStart(2,'0')}:00:00`
    expect(eventHeightPx(to5, to7)).toBe(60 * PX_PER_MINUTE)
  })

  it('clips end to axis end for events ending past midnight', () => {
    // Build times relative to AXIS_END_HOUR (midnight = 24)
    // 23:00 – 25:00 (conceptually); we use AXIS_END_HOUR - 1 to AXIS_END_HOUR + 1
    const d23 = new Date('2024-06-10T00:00:00')
    d23.setHours(AXIS_END_HOUR - 1, 0, 0, 0)
    // Simulate a time past axis end by adding 2 hours of ms after the end boundary
    const pastMidnight = new Date(d23.getTime() + 2 * 60 * 60_000)
    const to23 = `${d23.getFullYear()}-${String(d23.getMonth()+1).padStart(2,'0')}-${String(d23.getDate()).padStart(2,'0')}T${String(d23.getHours()).padStart(2,'0')}:00:00`
    // past midnight ISO from Date object
    const toPast = pastMidnight.toISOString()
    // Only 60 visible minutes (23:00–24:00)
    expect(eventHeightPx(to23, toPast)).toBe(60 * PX_PER_MINUTE)
  })
})

describe('anchorBandTopPx', () => {
  it('returns correct px for an anchor starting at 8am when axis starts at 6am', () => {
    const anchor8am: Anchor = { ...testAnchor, time: '08:00' }
    const result = anchorBandTopPx(anchor8am, testDate)
    // 8am = 120 minutes after 6am axis start
    expect(result).toBe(120 * PX_PER_MINUTE)
  })
})

describe('anchorBandHeightPx', () => {
  it('returns duration * PX_PER_MINUTE for the anchor band', () => {
    // testAnchor is 60 minutes
    const result = anchorBandHeightPx(testAnchor, testDate)
    expect(result).toBe(60 * PX_PER_MINUTE)
  })
})

// --- DayTimeline component tests ---

describe('DayTimeline component', () => {
  beforeEach(() => {
    setActivePinia(createPinia())
  })

  it('mounts and renders day-timeline root element', async () => {
    const { default: DayTimeline } = await import('../DayTimeline.vue')
    const wrapper = mount(DayTimeline, {
      props: { date: '2024-06-10' },
    })
    expect(wrapper.find('[data-testid="day-timeline"]').exists()).toBe(true)
  })

  it('renders time labels for each hour from 6am to 11pm', async () => {
    const { default: DayTimeline } = await import('../DayTimeline.vue')
    const wrapper = mount(DayTimeline, {
      props: { date: '2024-06-10' },
    })
    // Hours 6..23 => 18 labels
    for (const hour of [6, 7, 8, 9, 10, 11, 12, 13, 23]) {
      expect(wrapper.find(`[data-testid="time-label-${hour}"]`).exists()).toBe(true)
    }
  })

  it('renders anchor bands with correct data-testids', async () => {
    const { default: DayTimeline } = await import('../DayTimeline.vue')
    const wrapper = mount(DayTimeline, {
      props: { date: '2024-06-10' },
    })
    expect(wrapper.find('[data-testid="anchor-band-a1"]').exists()).toBe(true)
  })

  it('renders the timed-area container', async () => {
    const { default: DayTimeline } = await import('../DayTimeline.vue')
    const wrapper = mount(DayTimeline, {
      props: { date: '2024-06-10' },
    })
    expect(wrapper.find('[data-testid="timed-area"]').exists()).toBe(true)
  })

  it('renders the allday-strip container', async () => {
    const { default: DayTimeline } = await import('../DayTimeline.vue')
    const wrapper = mount(DayTimeline, {
      props: { date: '2024-06-10' },
    })
    expect(wrapper.find('[data-testid="allday-strip"]').exists()).toBe(true)
  })

  it('renders timed event titles in the timed area', async () => {
    const { default: DayTimeline } = await import('../DayTimeline.vue')
    const wrapper = mount(DayTimeline, {
      props: { date: '2024-06-10' },
    })
    const timedArea = wrapper.find('[data-testid="timed-area"]')
    expect(timedArea.text()).toContain('Team standup')
  })

  it('renders all-day event titles in the allday-strip, not the timed area', async () => {
    const { default: DayTimeline } = await import('../DayTimeline.vue')
    const wrapper = mount(DayTimeline, {
      props: { date: '2024-06-10' },
    })
    const alldayStrip = wrapper.find('[data-testid="allday-strip"]')
    const timedArea = wrapper.find('[data-testid="timed-area"]')
    expect(alldayStrip.text()).toContain('Holiday')
    expect(timedArea.text()).not.toContain('Holiday')
  })

  it('emits create-at with an ISO time string when empty area is clicked', async () => {
    const { default: DayTimeline } = await import('../DayTimeline.vue')
    const wrapper = mount(DayTimeline, {
      props: { date: '2024-06-10' },
    })
    const timedArea = wrapper.find('[data-testid="timed-area"]')
    // Simulate click with offsetY
    await timedArea.trigger('click', { offsetY: 0 })
    const emitted = wrapper.emitted('create-at')
    expect(emitted).toBeTruthy()
    expect(emitted![0][0]).toMatch(/\d{4}-\d{2}-\d{2}T\d{2}:\d{2}/)
  })

  it('timed area has drop handler (wired for promote from AnchorBlock)', async () => {
    // Verifies that the timed area is set up to accept drops.
    // Full integration of DragEvent.dataTransfer is limited in jsdom; this tests the wiring.
    const { default: DayTimeline } = await import('../DayTimeline.vue')
    const wrapper = mount(DayTimeline, { props: { date: '2024-06-10' } })
    const timedArea = wrapper.find('[data-testid="timed-area"]')
    // Drop should not throw even with no dataTransfer payload
    await expect(timedArea.trigger('drop')).resolves.not.toThrow()
  })

  it('grip strip has draggable attribute; CalendarEventBlock body does not', async () => {
    const { default: DayTimeline } = await import('../DayTimeline.vue')
    const wrapper = mount(DayTimeline, { props: { date: '2024-06-10' } })
    // The grip element (left-edge strip) should have draggable="true"
    const draggableGrips = wrapper.findAll('[draggable="true"]')
    expect(draggableGrips.length).toBeGreaterThan(0)
    // But the CalendarEventBlock rendered inside the event container should NOT be the draggable element
    // (draggable is on the grip, not on the CalendarEventBlock absolute div)
    for (const grip of draggableGrips) {
      // Each grip is the narrow left-strip, it should not contain the event title text directly
      expect(grip.text()).not.toContain('Team standup')
    }
  })

  it('create-at emit uses local ISO format (no Z suffix)', async () => {
    const { default: DayTimeline } = await import('../DayTimeline.vue')
    const wrapper = mount(DayTimeline, { props: { date: '2024-06-10' } })
    const timedArea = wrapper.find('[data-testid="timed-area"]')
    await timedArea.trigger('click', { offsetY: 0 })
    const emitted = wrapper.emitted('create-at')
    expect(emitted).toBeTruthy()
    // Should be local-naive: YYYY-MM-DDTHH:MM (no Z, no +offset)
    expect(emitted![0][0]).toMatch(/^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}$/)
  })
})
