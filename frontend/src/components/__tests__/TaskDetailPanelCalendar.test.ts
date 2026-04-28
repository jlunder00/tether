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
})
