import { describe, it, expect, vi, beforeEach, afterEach } from 'vitest'
import { ref, nextTick } from 'vue'
import { mount } from '@vue/test-utils'
import { createPinia, setActivePinia } from 'pinia'

// Full mock of vue-router
vi.mock('vue-router', () => ({
  useRouter: () => ({ push: vi.fn() }),
  useRoute: () => ({ path: '/', query: {} }),
  RouterLink: { template: '<a><slot /></a>' },
}))

// Mock all composables that touch the network
vi.mock('../../composables/useSubtasks', () => ({
  useSubtasks: () => ({ subtasks: { value: [] }, create: vi.fn(), update: vi.fn(), remove: vi.fn() }),
}))
vi.mock('../../composables/useLinks', () => ({
  useLinks: () => ({ links: { value: [] }, create: vi.fn(), remove: vi.fn() }),
}))
vi.mock('../../composables/useDependencies', () => {
  const { ref } = require('vue')
  return {
    useDependencies: () => ({ deps: ref({ blocked_by: [], blocks: [] }), add: vi.fn(), remove: vi.fn() }),
  }
})
vi.mock('../../composables/useTaskContexts', () => {
  const { ref } = require('vue')
  return {
    useTaskContexts: () => ({ contexts: ref([]), link: vi.fn(), unlink: vi.fn() }),
  }
})
vi.mock('../../composables/useSlideOver', () => ({
  useSlideOver: () => ({ push: vi.fn(), pop: vi.fn() }),
}))

// Mock api
vi.mock('../../lib/api', () => ({
  api: vi.fn(async () => ({ ok: true, json: async () => [] })),
}))

const today = new Date().toISOString().slice(0, 10)

// Mock stores that trigger async fetches in onMounted or have complex state
vi.mock('../../stores/plan', () => ({
  usePlanStore: () => ({
    plan: null,
    today,
    activeDate: today,
    fetchPlan: vi.fn(),
  }),
}))
vi.mock('../../stores/milestones', () => ({
  useMilestoneStore: () => ({
    all: [],
    taskMilestones: {},
    fetchAll: vi.fn(),
  }),
}))
vi.mock('../../stores/anchors', () => ({
  useAnchorStore: () => ({
    anchors: [],
    fetchAnchors: vi.fn(),
  }),
}))

// backlogStore is controlled per-test via a module-level ref so we can seed tasks
const backlogTasksRef = ref<any[]>([])
vi.mock('../../stores/backlog', () => ({
  useBacklogStore: () => ({
    get tasks() { return backlogTasksRef.value },
    fetchTasks: vi.fn(),
  }),
}))

const GLOBAL_STUBS = {
  SearchAutocomplete: true,
  RecurrencePicker: { template: '<div data-testid="recurrence-picker-stub" />' },
  'router-link': { template: '<a><slot /></a>' },
}

const MOCK_TASK = {
  id: 'task-1',
  text: 'Test task',
  status: 'pending',
  description: null,
  followup_config: null,
}

describe('TaskDetailPanel — Calendar section RecurrencePicker', () => {
  beforeEach(() => {
    setActivePinia(createPinia())
    backlogTasksRef.value = []
  })

  it('renders RecurrencePicker inside Calendar section when taskEvent exists', async () => {
    const { useEventStore } = await import('../../stores/events')
    const eventStore = useEventStore()

    // Seed task so it's found immediately (no async wait needed)
    backlogTasksRef.value = [MOCK_TASK]
    // Seed a calendar event linked to task-1
    eventStore.events.push({
      id: 'ev-1',
      title: 'Test task',
      start_time: '2024-06-10T09:00:00Z',
      end_time: '2024-06-10T10:00:00Z',
      source: 'tether',
      external_id: null,
      task_id: 'task-1',
      anchor_id: null,
      color: null,
      is_recurring: false,
      is_occurrence: false,
      is_all_day: false,
      rrule: null,
      context_subject: null,
    })

    const { default: TaskDetailPanel } = await import('../TaskDetailPanel.vue')
    const wrapper = mount(TaskDetailPanel, {
      props: { taskId: 'task-1' },
      global: { stubs: GLOBAL_STUBS },
    })

    await wrapper.vm.$nextTick()

    expect(wrapper.find('[data-testid="recurrence-picker-stub"]').exists()).toBe(true)
  })

  it('does not render RecurrencePicker when no taskEvent exists for this task', async () => {
    // Task exists but no calendar event is linked to it
    backlogTasksRef.value = [MOCK_TASK]

    const { default: TaskDetailPanel } = await import('../TaskDetailPanel.vue')
    const wrapper = mount(TaskDetailPanel, {
      props: { taskId: 'task-1' },
      global: { stubs: GLOBAL_STUBS },
    })

    await wrapper.vm.$nextTick()

    expect(wrapper.find('[data-testid="recurrence-picker-stub"]').exists()).toBe(false)
  })

  it('color input @input updates eventStore color for task-linked events (after debounce)', async () => {
    // Verifies the task-linked picker → store path works end-to-end.
    // onEventColorChange debounces 150 ms; fake timers are used to flush it.
    const { useEventStore } = await import('../../stores/events')
    const eventStore = useEventStore()

    backlogTasksRef.value = [MOCK_TASK]
    eventStore.events.push({
      id: 'ev-linked',
      title: 'Test task',
      start_time: '2024-06-10T09:00:00Z',
      end_time: '2024-06-10T10:00:00Z',
      source: 'tether' as const,
      external_id: null,
      task_id: 'task-1',
      anchor_id: null,
      color: null,
      is_recurring: false,
      is_occurrence: false,
      is_all_day: false,
      rrule: null,
      context_subject: null,
    })

    const { default: TaskDetailPanel } = await import('../TaskDetailPanel.vue')
    const wrapper = mount(TaskDetailPanel, {
      props: { taskId: 'task-1' },
      global: { stubs: GLOBAL_STUBS },
    })
    await wrapper.vm.$nextTick()

    const colorInput = wrapper.find('[data-testid="event-color-input"]')
    expect(colorInput.exists()).toBe(true)

    vi.useFakeTimers()
    try {
      // setValue triggers the input event synchronously
      await colorInput.setValue('#ff0000')
      // Advance timers past the 150 ms debounce window
      vi.runAllTimers()
      await wrapper.vm.$nextTick()
    } finally {
      vi.useRealTimers()
    }

    expect(eventStore.events.find(e => e.id === 'ev-linked')?.color).toBe('#ff0000')
  })

  // Bug 1: Standalone events (no task_id) opened via kind:'event' in SlideOverStack
  // pass their own event.id as the taskId prop. The current taskEvent computed only
  // searches by task_id — so taskEvent is null, and the color picker is hidden inside
  // the v-if="taskEvent" guard that never renders.
  it('color picker is visible when TaskDetailPanel receives a standalone event ID as taskId', async () => {
    const { useEventStore } = await import('../../stores/events')
    const eventStore = useEventStore()

    // Standalone event: task_id is null (no linked task)
    eventStore.events.push({
      id: 'ev-standalone',
      title: 'Standalone Calendar Event',
      start_time: '2024-06-10T14:00:00Z',
      end_time: '2024-06-10T15:00:00Z',
      source: 'tether' as const,
      external_id: null,
      task_id: null,
      anchor_id: null,
      color: '#ff6600',
      is_recurring: false,
      is_occurrence: false,
      is_all_day: false,
      rrule: null,
      context_subject: null,
    })

    const { default: TaskDetailPanel } = await import('../TaskDetailPanel.vue')
    // SlideOverStack passes event.id as task-id for kind:'event' panels
    const wrapper = mount(TaskDetailPanel, {
      props: { taskId: 'ev-standalone' },
      global: { stubs: GLOBAL_STUBS },
    })
    await wrapper.vm.$nextTick()

    // Color picker must be visible so the user can change the event's color
    expect(wrapper.find('[data-testid="event-color-input"]').exists()).toBe(true)
  })

  it('changing color picker for standalone event updates eventStore color (after debounce)', async () => {
    const { useEventStore } = await import('../../stores/events')
    const eventStore = useEventStore()

    eventStore.events.push({
      id: 'ev-standalone-2',
      title: 'Another Standalone Event',
      start_time: '2024-06-10T14:00:00Z',
      end_time: '2024-06-10T15:00:00Z',
      source: 'tether' as const,
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

    const { default: TaskDetailPanel } = await import('../TaskDetailPanel.vue')
    const wrapper = mount(TaskDetailPanel, {
      props: { taskId: 'ev-standalone-2' },
      global: { stubs: GLOBAL_STUBS },
    })
    await wrapper.vm.$nextTick()

    const colorInput = wrapper.find('[data-testid="event-color-input"]')
    expect(colorInput.exists()).toBe(true)

    vi.useFakeTimers()
    try {
      await colorInput.setValue('#00aaff')
      vi.runAllTimers()
      await wrapper.vm.$nextTick()
    } finally {
      vi.useRealTimers()
    }

    expect(eventStore.events.find(e => e.id === 'ev-standalone-2')?.color).toBe('#00aaff')
  })
})

// ─── Recurring-event color scope dialog ───────────────────────────────────────
// Bug 1+3: Color changes on recurring events must gate behind RecurrenceEditDialog
// before issuing any PATCH so the user can choose 'this' / 'future' / 'all'.
// The dialog is teleported to document.body — tests must use attachTo.

const RECURRING_EVENT = {
  id: 'ev-recurring',
  title: 'Weekly meeting',
  start_time: '2024-06-10T09:00:00Z',
  end_time: '2024-06-10T10:00:00Z',
  source: 'tether' as const,
  external_id: null,
  task_id: 'task-1',
  anchor_id: null,
  color: null,
  is_recurring: true,
  is_occurrence: false,
  is_all_day: false,
  rrule: 'FREQ=WEEKLY;BYDAY=MO',
  context_subject: null,
}

describe('TaskDetailPanel — Color change scope dialog for recurring events', () => {
  beforeEach(() => {
    setActivePinia(createPinia())
    backlogTasksRef.value = []
  })

  afterEach(() => {
    // Remove all children added by Teleport/attachTo without using innerHTML
    while (document.body.firstChild) {
      document.body.removeChild(document.body.firstChild)
    }
  })

  // Contract / green-anchor: non-recurring event color change calls PATCH immediately.
  it('non-recurring: color change calls PATCH /api/events/:id with color payload', async () => {
    const { api } = await import('../../lib/api')
    const { useEventStore } = await import('../../stores/events')
    const eventStore = useEventStore()

    backlogTasksRef.value = [MOCK_TASK]
    eventStore.events.push({
      id: 'ev-nonrecurring',
      title: 'Test task',
      start_time: '2024-06-10T09:00:00Z',
      end_time: '2024-06-10T10:00:00Z',
      source: 'tether' as const,
      external_id: null,
      task_id: 'task-1',
      anchor_id: null,
      color: null,
      is_recurring: false,
      is_occurrence: false,
      is_all_day: false,
      rrule: null,
      context_subject: null,
    })

    const { default: TaskDetailPanel } = await import('../TaskDetailPanel.vue')
    const wrapper = mount(TaskDetailPanel, {
      props: { taskId: 'task-1' },
      global: { stubs: GLOBAL_STUBS },
    })
    await wrapper.vm.$nextTick()

    vi.useFakeTimers()
    try {
      await wrapper.find('[data-testid="event-color-input"]').setValue('#aa3300')
      vi.runAllTimers()
      await wrapper.vm.$nextTick()
    } finally {
      vi.useRealTimers()
    }

    // PATCH must have been called with the color in the body
    const patchCall = (api as ReturnType<typeof vi.fn>).mock.calls.find(
      (args: any[]) =>
        typeof args[0] === 'string' && args[0].includes('ev-nonrecurring') && args[1]?.method === 'PATCH',
    )
    expect(patchCall).toBeDefined()
    const body = JSON.parse(patchCall![1].body)
    expect(body.color).toBe('#aa3300')
  })

  // Recurring event: color change via @change must show the scope dialog, NOT patch immediately.
  it('recurring: color change shows RecurrenceEditDialog instead of patching immediately', async () => {
    const { api } = await import('../../lib/api')
    const { useEventStore } = await import('../../stores/events')
    const eventStore = useEventStore()

    backlogTasksRef.value = [MOCK_TASK]
    eventStore.events.push({ ...RECURRING_EVENT })

    const { default: TaskDetailPanel } = await import('../TaskDetailPanel.vue')
    const wrapper = mount(TaskDetailPanel, {
      props: { taskId: 'task-1' },
      global: { stubs: { ...GLOBAL_STUBS, RecurrenceEditDialog: false } },
      attachTo: document.body,
    })
    await wrapper.vm.$nextTick()

    // Trigger the color picker's change event (fires on dismiss, not during drag).
    // vue-test-utils forbids setting target.value in trigger(); set the element
    // property directly first, then dispatch the event.
    const colorInput = wrapper.find('[data-testid="event-color-input"]')
    expect(colorInput.exists()).toBe(true)
    ;(colorInput.element as HTMLInputElement).value = '#ff0000'
    await colorInput.trigger('change')
    await nextTick()

    // Dialog must be visible
    expect(document.body.querySelector('[data-testid="recurrence-edit-dialog"]')).not.toBeNull()

    // No PATCH must have been sent yet
    const patchCalls = (api as ReturnType<typeof vi.fn>).mock.calls.filter(
      (args: any[]) =>
        typeof args[0] === 'string' && args[0].includes('ev-recurring') && args[1]?.method === 'PATCH',
    )
    expect(patchCalls).toHaveLength(0)

    wrapper.unmount()
  })

  // Recurring event: confirming the scope dialog sends PATCH with color + scope.
  it('recurring: confirming scope dialog sends PATCH with color and scope', async () => {
    const { api } = await import('../../lib/api')
    const { useEventStore } = await import('../../stores/events')
    const eventStore = useEventStore()

    backlogTasksRef.value = [MOCK_TASK]
    eventStore.events.push({ ...RECURRING_EVENT })

    const { default: TaskDetailPanel } = await import('../TaskDetailPanel.vue')
    const wrapper = mount(TaskDetailPanel, {
      props: { taskId: 'task-1' },
      global: { stubs: { ...GLOBAL_STUBS, RecurrenceEditDialog: false } },
      attachTo: document.body,
    })
    await wrapper.vm.$nextTick()

    // Open the scope dialog
    const colorInput = wrapper.find('[data-testid="event-color-input"]')
    ;(colorInput.element as HTMLInputElement).value = '#bb2200'
    await colorInput.trigger('change')
    await nextTick()

    // Select 'this_and_future' scope and confirm
    const futureRadio = document.body.querySelector('[data-testid="scope-future"]') as HTMLInputElement
    if (futureRadio) {
      futureRadio.click()
      await nextTick()
    }
    const confirmBtn = document.body.querySelector('[data-testid="recurrence-edit-confirm"]') as HTMLElement
    expect(confirmBtn).not.toBeNull()
    confirmBtn.click()
    await nextTick()

    // PATCH must have been called with color and scope
    const patchCall = (api as ReturnType<typeof vi.fn>).mock.calls.find(
      (args: any[]) =>
        typeof args[0] === 'string' && args[0].includes('ev-recurring') && args[1]?.method === 'PATCH',
    )
    expect(patchCall).toBeDefined()
    const body = JSON.parse(patchCall![1].body)
    expect(body.color).toBe('#bb2200')
    expect(body.scope).toBe('this_and_future')

    wrapper.unmount()
  })

  // Recurring event: cancelling the scope dialog leaves the store color unchanged.
  it('recurring: cancelling scope dialog leaves event color unchanged in store', async () => {
    const { useEventStore } = await import('../../stores/events')
    const eventStore = useEventStore()

    backlogTasksRef.value = [MOCK_TASK]
    eventStore.events.push({ ...RECURRING_EVENT })

    const { default: TaskDetailPanel } = await import('../TaskDetailPanel.vue')
    const wrapper = mount(TaskDetailPanel, {
      props: { taskId: 'task-1' },
      global: { stubs: { ...GLOBAL_STUBS, RecurrenceEditDialog: false } },
      attachTo: document.body,
    })
    await wrapper.vm.$nextTick()

    // Open the scope dialog
    const colorInput = wrapper.find('[data-testid="event-color-input"]')
    ;(colorInput.element as HTMLInputElement).value = '#cc1100'
    await colorInput.trigger('change')
    await nextTick()

    // Cancel the dialog
    const cancelBtn = document.body.querySelector('[data-testid="recurrence-edit-cancel"]') as HTMLElement
    expect(cancelBtn).not.toBeNull()
    cancelBtn.click()
    await nextTick()

    // Store color must remain null — no phantom optimistic update
    expect(eventStore.events.find(e => e.id === 'ev-recurring')?.color).toBeNull()

    wrapper.unmount()
  })
})
