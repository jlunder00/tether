import { describe, it, expect, vi, beforeEach } from 'vitest'
import { mount, flushPromises } from '@vue/test-utils'
import { createPinia, setActivePinia } from 'pinia'
import { defineComponent, h, nextTick } from 'vue'
import { resetFocusedDay } from '../../composables/useCalendarFocus'

// Lightweight stub for router-link so we can test nav rendering
vi.mock('vue-router', () => ({
  useRouter: () => ({ push: vi.fn(), back: vi.fn() }),
  useRoute: () => ({ path: '/calendar', query: {} }),
  RouterLink: defineComponent({
    props: ['to'],
    setup(props, { slots }) {
      return () => h('a', { href: typeof props.to === 'string' ? props.to : props.to?.path ?? '#' }, slots.default?.())
    },
  }),
  RouterView: defineComponent({ template: '<div />' }),
}))

// Stub API so store actions don't fire real requests
vi.mock('../../lib/api', () => ({
  api: vi.fn(() => Promise.resolve({ ok: true, json: async () => [] })),
}))

describe('CalendarView', () => {
  beforeEach(() => {
    setActivePinia(createPinia())
    resetFocusedDay()
  })

  it('renders a top-level heading with "Calendar"', async () => {
    const { default: CalendarView } = await import('../CalendarView.vue')
    const wrapper = mount(CalendarView)
    expect(wrapper.text()).toMatch(/Calendar/i)
  })

  it('renders the week time-grid container', async () => {
    const { default: CalendarView } = await import('../CalendarView.vue')
    const wrapper = mount(CalendarView)
    // The grid must exist in the DOM — identified by data-testid
    expect(wrapper.find('[data-testid="calendar-grid"]').exists()).toBe(true)
  })

  it('renders an anchor panel section', async () => {
    const { default: CalendarView } = await import('../CalendarView.vue')
    const wrapper = mount(CalendarView)
    expect(wrapper.find('[data-testid="anchor-panel"]').exists()).toBe(true)
  })

  it('can collapse and expand the anchor panel', async () => {
    const { default: CalendarView } = await import('../CalendarView.vue')
    const wrapper = mount(CalendarView)
    const toggle = wrapper.find('[data-testid="anchor-panel-toggle"]')
    expect(toggle.exists()).toBe(true)
    await toggle.trigger('click')
    expect(wrapper.find('[data-testid="anchor-panel-content"]').exists()).toBe(false)
    await toggle.trigger('click')
    expect(wrapper.find('[data-testid="anchor-panel-content"]').exists()).toBe(true)
  })

  it('clicking a day header sets that day as focused', async () => {
    const { default: CalendarView } = await import('../CalendarView.vue')
    const wrapper = mount(CalendarView)
    // Find all day header cells (there are 7)
    const headers = wrapper.findAll('[data-testid^="day-header-"]')
    expect(headers.length).toBe(7)
    // Click the second day header
    await headers[1].trigger('click')
    await nextTick()
    // That header should now carry the focused-day marker
    expect(headers[1].attributes('data-focused')).toBe('true')
    // Other headers should not be focused
    expect(headers[0].attributes('data-focused')).not.toBe('true')
  })

  it('the focused day column receives the focused-day highlight', async () => {
    const { default: CalendarView } = await import('../CalendarView.vue')
    const wrapper = mount(CalendarView)
    const headers = wrapper.findAll('[data-testid^="day-header-"]')
    await headers[2].trigger('click')
    await nextTick()
    const dayKey = headers[2].attributes('data-day')!
    const col = wrapper.find(`[data-testid="day-col-${dayKey}"]`)
    expect(col.exists()).toBe(true)
    expect(col.classes()).toContain('ring-inset')
  })

  it('anchor panel content uses block layout (not flex-col) so tasks are not squished', async () => {
    const { default: CalendarView } = await import('../CalendarView.vue')
    const wrapper = mount(CalendarView)
    const content = wrapper.find('[data-testid="anchor-panel-content"]')
    expect(content.classes()).not.toContain('flex')
  })

  it('defaults to week view — week-view container is visible', async () => {
    const { default: CalendarView } = await import('../CalendarView.vue')
    const wrapper = mount(CalendarView)
    expect(wrapper.find('[data-testid="week-view"]').exists()).toBe(true)
    expect(wrapper.find('[data-testid="month-view"]').exists()).toBe(false)
  })

  it('clicking Week/Month toggle switches to month view', async () => {
    const { default: CalendarView } = await import('../CalendarView.vue')
    const wrapper = mount(CalendarView)
    const toggle = wrapper.find('[data-testid="view-mode-toggle"]')
    expect(toggle.exists()).toBe(true)
    await toggle.trigger('click')
    await nextTick()
    expect(wrapper.find('[data-testid="month-view"]').exists()).toBe(true)
    expect(wrapper.find('[data-testid="week-view"]').exists()).toBe(false)
  })

  it('clicking a month day cell switches back to week view and shows that day focused', async () => {
    const { default: CalendarView } = await import('../CalendarView.vue')
    const wrapper = mount(CalendarView)
    // Switch to month
    await wrapper.find('[data-testid="view-mode-toggle"]').trigger('click')
    await nextTick()
    // Click the first day cell
    const cell = wrapper.find('[data-testid^="month-day-"]')
    expect(cell.exists()).toBe(true)
    const dayKey = cell.attributes('data-day')!
    await cell.trigger('click')
    await nextTick()
    expect(wrapper.find('[data-testid="week-view"]').exists()).toBe(true)
    // Focused day header should reflect that day
    const focusedHeader = wrapper.find('[data-focused="true"]')
    expect(focusedHeader.attributes('data-day')).toBe(dayKey)
  })

  it('tag filter: eventsByDay excludes events not matching selected context node', async () => {
    const { useEventStore } = await import('../../stores/events')
    const { useMilestoneStore } = await import('../../stores/milestones')
    const { useContextStore } = await import('../../stores/context')
    const { default: CalendarView } = await import('../CalendarView.vue')

    const wrapper = mount(CalendarView)
    // Wait for onMounted fetchEvents to complete (it resets events.value = [])
    await flushPromises()

    const eventStore = useEventStore()
    const milestoneStore = useMilestoneStore()
    const contextStore = useContextStore()

    // Seed a milestone context node (node_type='milestone') that owns task-a
    contextStore.nodes['ms-1'] = {
      id: 'ms-1',
      parent_id: null,
      name: 'Sprint 1',
      description: null,
      node_type: 'milestone',
      archived: false,
      target_date: null,
      status: 'pending',
      status_override: false,
      color: '#6366f1',
      created_at: '',
      updated_at: '',
    }
    milestoneStore.all.push({
      id: 'ms-1',
      context_subject: 'project-x',
      name: 'Sprint 1',
      description: null,
      target_date: null,
      status: 'pending',
      status_override: false,
      color: '#6366f1',
      created_at: '',
      updated_at: '',
      task_count: 1,
      done_count: 0,
      task_ids: ['task-a'],
      tasks: [],
    })

    // Compute today's local date string the same way CalendarView does
    const d = new Date()
    const TODAY = `${d.getFullYear()}-${String(d.getMonth() + 1).padStart(2, '0')}-${String(d.getDate()).padStart(2, '0')}`

    // Seed events AFTER flushPromises so fetchEvents doesn't wipe them
    eventStore.events.push(
      {
        id: 'ev-a',
        title: 'Event A (in milestone)',
        start_time: `${TODAY}T09:00:00`,
        end_time: `${TODAY}T10:00:00`,
        source: 'tether',
        external_id: null,
        task_id: 'task-a',
        anchor_id: null,
        color: null,
        is_recurring: false,
        is_occurrence: false,
        is_all_day: false,
        rrule: null,
        context_subject: null,
      },
      {
        id: 'ev-b',
        title: 'Event B (no milestone)',
        start_time: `${TODAY}T11:00:00`,
        end_time: `${TODAY}T12:00:00`,
        source: 'tether',
        external_id: null,
        task_id: 'task-b',
        anchor_id: null,
        color: null,
        is_recurring: false,
        is_occurrence: false,
        is_all_day: false,
        rrule: null,
        context_subject: null,
      },
    )
    await nextTick()

    // Before filter: both events should appear in week view
    expect(wrapper.text()).toContain('Event A (in milestone)')
    expect(wrapper.text()).toContain('Event B (no milestone)')

    // Open filter dropdown and activate context node filter for Sprint 1
    await wrapper.find('[data-testid="filter-button"]').trigger('click')
    await nextTick()
    // Sprint 1 is rendered via ContextTreeFilterNode in Teleport — use data-testid
    const sprintBtn = document.querySelector('[data-testid="filter-item-context-ms-1"]') as HTMLElement | null
    expect(sprintBtn).not.toBeNull()
    sprintBtn!.click()
    await nextTick()

    // After filter: only Event A should appear in the week grid
    expect(wrapper.text()).toContain('Event A (in milestone)')
    expect(wrapper.text()).not.toContain('Event B (no milestone)')
  })

  it('drag threshold no-op: mouseup with <5px movement does not call moveEvent', async () => {
    const { useEventStore } = await import('../../stores/events')
    const { default: CalendarView } = await import('../CalendarView.vue')
    mount(CalendarView)
    await flushPromises()

    const eventStore = useEventStore()
    const moveSpy = vi.spyOn(eventStore, 'moveEvent')

    // Seed an event block
    const d = new Date()
    const TODAY = `${d.getFullYear()}-${String(d.getMonth() + 1).padStart(2, '0')}-${String(d.getDate()).padStart(2, '0')}`
    eventStore.events.push({
      id: 'ev-drag',
      title: 'Drag test',
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

    // Simulate mousedown then mouseup with no movement (below threshold)
    window.dispatchEvent(new MouseEvent('mousedown', { clientX: 100, clientY: 200 }))
    window.dispatchEvent(new MouseEvent('mouseup', { clientX: 101, clientY: 201 })) // <5px
    await nextTick()

    expect(moveSpy).not.toHaveBeenCalled()
  })

  it('all-day band renders when is_all_day events exist', async () => {
    const { useEventStore } = await import('../../stores/events')
    const { default: CalendarView } = await import('../CalendarView.vue')
    const wrapper = mount(CalendarView)
    await flushPromises()

    const d = new Date()
    const TODAY = `${d.getFullYear()}-${String(d.getMonth() + 1).padStart(2, '0')}-${String(d.getDate()).padStart(2, '0')}`
    useEventStore().events.push({
      id: 'ev-allday',
      title: 'All Day Event',
      start_time: `${TODAY}T00:00:00`,
      end_time: `${TODAY}T23:59:59`,
      source: 'tether',
      external_id: null,
      task_id: null,
      anchor_id: null,
      color: null,
      is_recurring: false,
      is_occurrence: false,
      is_all_day: true,
      rrule: null,
      context_subject: null,
    })
    await nextTick()

    expect(wrapper.find('[data-testid="all-day-band"]').exists()).toBe(true)
    expect(wrapper.text()).toContain('All Day Event')
  })

  it('all-day band has sticky class so it does not scroll away', async () => {
    const { default: CalendarView } = await import('../CalendarView.vue')
    const wrapper = mount(CalendarView)
    const band = wrapper.find('[data-testid="all-day-band"]')
    expect(band.exists()).toBe(true)
    expect(band.classes()).toContain('sticky')
  })

  it('overlap-background band appears when two timed events overlap in the same day column', async () => {
    const { useEventStore } = await import('../../stores/events')
    const { default: CalendarView } = await import('../CalendarView.vue')
    const wrapper = mount(CalendarView)
    await flushPromises()

    const d = new Date()
    const TODAY = `${d.getFullYear()}-${String(d.getMonth() + 1).padStart(2, '0')}-${String(d.getDate()).padStart(2, '0')}`

    // Seed two timed events that overlap in the same day
    useEventStore().events.push(
      {
        id: 'ev-ov1',
        title: 'Event Overlap 1',
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
      },
      {
        id: 'ev-ov2',
        title: 'Event Overlap 2',
        start_time: `${TODAY}T09:30:00`,
        end_time: `${TODAY}T10:30:00`,
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
      },
    )
    await nextTick()

    expect(wrapper.find('[data-testid="overlap-background"]').exists()).toBe(true)
  })

  it('event block backgroundColor updates reactively when ev.color is mutated in the store', async () => {
    // Bug 1: color picker in TaskDetailPanel calls updateEventColor which mutates ev.color;
    // the CalendarView template must re-render and pass the new resolvedColor to CalendarEventBlock.
    const { useEventStore } = await import('../../stores/events')
    const { default: CalendarView } = await import('../CalendarView.vue')
    const wrapper = mount(CalendarView)
    await flushPromises()

    const d = new Date()
    const TODAY = `${d.getFullYear()}-${String(d.getMonth() + 1).padStart(2, '0')}-${String(d.getDate()).padStart(2, '0')}`

    const eventStore = useEventStore()
    // Seed a tether event with no custom color (will render with default indigo #6366f1)
    eventStore.events.push({
      id: 'ev-color-test',
      title: 'Color Reactive Test',
      start_time: `${TODAY}T10:00:00`,
      end_time: `${TODAY}T11:00:00`,
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

    // Verify the event block is rendered
    const block = wrapper.find('[data-event-block]')
    expect(block.exists()).toBe(true)

    // Mutate the color directly on the reactive store object (as updateEventColor does)
    const ev = eventStore.events.find(e => e.id === 'ev-color-test')!
    ev.color = '#ff0000'
    await nextTick()

    // The CalendarEventBlock's resolvedColor prop is recomputed via the template's
    // resolveColor(event) call, which reads event.color — a reactive dependency.
    // Therefore the block's backgroundColor should now be '#ff0000'.
    // Note: JSDOM preserves hex literals; real browsers normalize to rgb().
    const updatedBlock = wrapper.find('[data-event-block]')
    expect(updatedBlock.attributes('style')).toContain('background-color: #ff0000')
  })
})
