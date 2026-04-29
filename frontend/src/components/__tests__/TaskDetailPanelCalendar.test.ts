import { describe, it, expect, vi, beforeEach } from 'vitest'
import { ref } from 'vue'
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

  it('color input @change updates eventStore color for task-linked events', async () => {
    // Verifies the task-linked picker → store path works end-to-end.
    // If this test PASSES the reactive chain is intact and Bug 1 is
    // confined to the standalone-event case (event ID passed as taskId).
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

    // setValue triggers both input and change events in Vue Test Utils
    await colorInput.setValue('#ff0000')

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

  it('changing color picker for standalone event updates eventStore color', async () => {
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
    await colorInput.setValue('#00aaff')

    expect(eventStore.events.find(e => e.id === 'ev-standalone-2')?.color).toBe('#00aaff')
  })
})
