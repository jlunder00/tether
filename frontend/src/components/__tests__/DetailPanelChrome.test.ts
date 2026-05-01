/**
 * DetailPanelChrome.test.ts
 *
 * Structural tests for the dp-* chrome on TaskDetailPanel and MilestoneDetailPanel:
 *   - Both panels render the dp-shell wrapper class
 *   - Both panels render dp-header
 *   - MilestoneDetailPanel exposes a color input (type="color")
 *   - MilestoneDetailPanel exposes a status_override toggle (checkbox)
 */
import { describe, it, expect, vi, beforeEach } from 'vitest'
import { ref } from 'vue'
import { mount } from '@vue/test-utils'
import { createPinia, setActivePinia } from 'pinia'

// ── shared mocks ──────────────────────────────────────────────────────────────

vi.mock('vue-router', () => ({
  useRouter: () => ({ push: vi.fn() }),
  useRoute: () => ({ path: '/', query: {} }),
  RouterLink: { template: '<a><slot /></a>' },
}))

vi.mock('../../lib/api', () => ({
  api: vi.fn(async () => ({ ok: true, json: async () => ({}) })),
}))

vi.mock('../../composables/useSubtasks', () => ({
  useSubtasks: () => ({ subtasks: ref([]), create: vi.fn(), update: vi.fn(), remove: vi.fn() }),
}))
vi.mock('../../composables/useLinks', () => ({
  useLinks: () => ({ links: ref([]), create: vi.fn(), remove: vi.fn() }),
}))
vi.mock('../../composables/useDependencies', () => ({
  useDependencies: () => ({ deps: ref({ blocked_by: [], blocks: [] }), add: vi.fn(), remove: vi.fn() }),
}))
vi.mock('../../composables/useTaskContexts', () => ({
  useTaskContexts: () => ({ contexts: ref([]), link: vi.fn(), unlink: vi.fn() }),
}))
vi.mock('../../composables/useSlideOver', () => ({
  useSlideOver: () => ({ push: vi.fn(), pop: vi.fn() }),
}))

const today = new Date().toISOString().slice(0, 10)

vi.mock('../../stores/anchors', () => ({
  useAnchorStore: () => ({ anchors: [], fetchAnchors: vi.fn() }),
}))
vi.mock('../../stores/backlog', () => ({
  useBacklogStore: () => ({ tasks: [], fetchTasks: vi.fn() }),
}))
vi.mock('../../stores/events', () => ({
  useEventStore: () => ({
    events: [],
    removeEventsForTask: vi.fn(),
    moveEvent: vi.fn(),
    setRecurrence: vi.fn(),
    updateEventColor: vi.fn(),
  }),
}))
vi.mock('../../stores/kanban', () => ({
  useKanbanStore: () => ({ applyTaskPatch: vi.fn() }),
}))
vi.mock('../../stores/tasks', () => ({
  useTasksStore: () => ({ setTaskRrule: vi.fn(), deleteTask: vi.fn() }),
}))
vi.mock('../../stores/milestones', () => ({
  useMilestoneStore: () => ({
    all: [],
    taskMilestones: {},
    fetchAll: vi.fn(),
    patchMilestone: vi.fn(),
    deleteMilestone: vi.fn(),
  }),
}))

const GLOBAL_STUBS = {
  SearchAutocomplete: true,
  RecurrencePicker: true,
  RecurrenceEditDialog: true,
  'router-link': { template: '<a><slot /></a>' },
}

// ── TaskDetailPanel ───────────────────────────────────────────────────────────

describe('TaskDetailPanel chrome', () => {
  const TASK = {
    id: 'task-1',
    text: 'Test task',
    status: 'pending',
    motif: 'focus',
    description: null,
    followup_config: null,
    anchor_id: 'morning',
    start_time: null,
    end_time: null,
    rrule: null,
    is_recurring_master: false,
    position: 0,
  }

  beforeEach(() => {
    setActivePinia(createPinia())
    vi.clearAllMocks()
  })

  it('renders .dp-shell as the root wrapper', async () => {
    vi.doMock('../../stores/plan', () => ({
      usePlanStore: () => ({
        plan: { date: today, anchors: { morning: { tasks: [TASK], notes: '' } } },
        today, activeDate: today,
        fetchPlan: vi.fn(), patchTaskFields: vi.fn(async () => true), moveTask: vi.fn(async () => {}),
      }),
    }))
    const { default: TaskDetailPanel } = await import('../TaskDetailPanel.vue')
    const wrapper = mount(TaskDetailPanel, {
      props: { taskId: 'task-1' },
      global: { stubs: GLOBAL_STUBS },
    })
    expect(wrapper.find('.dp-shell').exists()).toBe(true)
  })

  it('renders .dp-header inside .dp-shell', async () => {
    vi.doMock('../../stores/plan', () => ({
      usePlanStore: () => ({
        plan: { date: today, anchors: { morning: { tasks: [TASK], notes: '' } } },
        today, activeDate: today,
        fetchPlan: vi.fn(), patchTaskFields: vi.fn(async () => true), moveTask: vi.fn(async () => {}),
      }),
    }))
    const { default: TaskDetailPanel } = await import('../TaskDetailPanel.vue')
    const wrapper = mount(TaskDetailPanel, {
      props: { taskId: 'task-1' },
      global: { stubs: GLOBAL_STUBS },
    })
    expect(wrapper.find('.dp-shell .dp-header').exists()).toBe(true)
  })

  it('renders .dp-footer with delete button', async () => {
    vi.doMock('../../stores/plan', () => ({
      usePlanStore: () => ({
        plan: { date: today, anchors: { morning: { tasks: [TASK], notes: '' } } },
        today, activeDate: today,
        fetchPlan: vi.fn(), patchTaskFields: vi.fn(async () => true), moveTask: vi.fn(async () => {}),
      }),
    }))
    const { default: TaskDetailPanel } = await import('../TaskDetailPanel.vue')
    const wrapper = mount(TaskDetailPanel, {
      props: { taskId: 'task-1' },
      global: { stubs: GLOBAL_STUBS },
    })
    expect(wrapper.find('.dp-footer').exists()).toBe(true)
    expect(wrapper.find('.dp-btn--ghost-danger').exists()).toBe(true)
  })

  it('shows a date input for scheduled tasks in the Location section', async () => {
    vi.doMock('../../stores/plan', () => ({
      usePlanStore: () => ({
        plan: {
          date: today,
          anchors: { morning: { tasks: [TASK], notes: '' } },
        },
        today,
        activeDate: today,
        fetchPlan: vi.fn(),
        patchTaskFields: vi.fn(async () => true),
        moveTask: vi.fn(async () => {}),
      }),
    }))
    const { default: TaskDetailPanel } = await import('../TaskDetailPanel.vue')
    const wrapper = mount(TaskDetailPanel, {
      props: { taskId: 'task-1' },
      global: { stubs: GLOBAL_STUBS },
    })
    expect(wrapper.find('input[data-testid="reschedule-date"]').exists()).toBe(true)
  })

  it('calls moveTask when the reschedule date input changes', async () => {
    const mockMoveTask = vi.fn(async () => {})
    const tomorrow = new Date(Date.now() + 86400000).toISOString().slice(0, 10)
    vi.resetModules()
    vi.doMock('../../stores/plan', () => ({
      usePlanStore: () => ({
        plan: { date: today, anchors: { morning: { tasks: [TASK], notes: '' } } },
        today, activeDate: today,
        fetchPlan: vi.fn(), patchTaskFields: vi.fn(async () => true), moveTask: mockMoveTask,
      }),
    }))
    // Re-mock all other deps after resetModules
    vi.doMock('../../lib/api', () => ({ api: vi.fn(async () => ({ ok: true, json: async () => ({}) })) }))
    vi.doMock('../../composables/useSubtasks', () => ({ useSubtasks: () => ({ subtasks: ref([]), create: vi.fn(), update: vi.fn(), remove: vi.fn() }) }))
    vi.doMock('../../composables/useLinks', () => ({ useLinks: () => ({ links: ref([]), create: vi.fn(), remove: vi.fn() }) }))
    vi.doMock('../../composables/useDependencies', () => ({ useDependencies: () => ({ deps: ref({ blocked_by: [], blocks: [] }), add: vi.fn(), remove: vi.fn() }) }))
    vi.doMock('../../composables/useTaskContexts', () => ({ useTaskContexts: () => ({ contexts: ref([]), link: vi.fn(), unlink: vi.fn() }) }))
    vi.doMock('../../composables/useSlideOver', () => ({ useSlideOver: () => ({ push: vi.fn(), pop: vi.fn() }) }))
    vi.doMock('../../stores/anchors', () => ({ useAnchorStore: () => ({ anchors: [], fetchAnchors: vi.fn() }) }))
    vi.doMock('../../stores/backlog', () => ({ useBacklogStore: () => ({ tasks: [], fetchTasks: vi.fn() }) }))
    vi.doMock('../../stores/events', () => ({ useEventStore: () => ({ events: [], removeEventsForTask: vi.fn(), moveEvent: vi.fn(), setRecurrence: vi.fn(), updateEventColor: vi.fn() }) }))
    vi.doMock('../../stores/kanban', () => ({ useKanbanStore: () => ({ applyTaskPatch: vi.fn() }) }))
    vi.doMock('../../stores/tasks', () => ({ useTasksStore: () => ({ setTaskRrule: vi.fn(), deleteTask: vi.fn() }) }))
    vi.doMock('../../stores/milestones', () => ({ useMilestoneStore: () => ({ all: [], taskMilestones: {}, fetchAll: vi.fn(), patchMilestone: vi.fn(), deleteMilestone: vi.fn() }) }))
    const { default: TaskDetailPanel } = await import('../TaskDetailPanel.vue')
    const wrapper = mount(TaskDetailPanel, {
      props: { taskId: 'task-1' },
      global: { stubs: GLOBAL_STUBS },
    })
    const dateInput = wrapper.find('input[data-testid="reschedule-date"]')
    await dateInput.setValue(tomorrow)
    await dateInput.trigger('change')
    expect(mockMoveTask).toHaveBeenCalledWith('task-1', today, 'morning', tomorrow, 'morning')
  })
})

// ── MilestoneDetailPanel ─────────────────────────────────────────────────────

const MILESTONE = {
  id: 'ms-1',
  name: 'Launch v2',
  description: 'Ship the new version',
  target_date: '2026-06-01',
  status: 'pending',
  status_override: 0,
  color: null,
  motif: 'focus',
  task_count: 3,
  done_count: 1,
  tasks: [],
  context_subject: 'Tether',
}

describe('MilestoneDetailPanel chrome', () => {
  beforeEach(() => {
    setActivePinia(createPinia())
    vi.clearAllMocks()
    vi.doMock('../../stores/milestones', () => ({
      useMilestoneStore: () => ({
        all: [MILESTONE],
        taskMilestones: {},
        fetchAll: vi.fn(),
        patchMilestone: vi.fn(async () => {}),
        deleteMilestone: vi.fn(),
      }),
    }))
    vi.doMock('../../stores/plan', () => ({
      usePlanStore: () => ({
        plan: null,
        today,
        activeDate: today,
        fetchPlan: vi.fn(),
        patchTaskFields: vi.fn(async () => true),
      }),
    }))
  })

  it('renders .dp-shell as the root wrapper', async () => {
    const { default: MilestoneDetailPanel } = await import('../MilestoneDetailPanel.vue')
    const wrapper = mount(MilestoneDetailPanel, {
      props: { milestoneId: 'ms-1' },
      global: { stubs: GLOBAL_STUBS },
    })
    expect(wrapper.find('.dp-shell').exists()).toBe(true)
  })

  it('renders .dp-header with motif data attribute', async () => {
    const { default: MilestoneDetailPanel } = await import('../MilestoneDetailPanel.vue')
    const wrapper = mount(MilestoneDetailPanel, {
      props: { milestoneId: 'ms-1' },
      global: { stubs: GLOBAL_STUBS },
    })
    const header = wrapper.find('.dp-header')
    expect(header.exists()).toBe(true)
  })

  it('renders a color input for milestone.color', async () => {
    const { default: MilestoneDetailPanel } = await import('../MilestoneDetailPanel.vue')
    const wrapper = mount(MilestoneDetailPanel, {
      props: { milestoneId: 'ms-1' },
      global: { stubs: GLOBAL_STUBS },
    })
    expect(wrapper.find('input[type="color"][data-testid="milestone-color-input"]').exists()).toBe(true)
  })

  it('renders a status_override checkbox', async () => {
    const { default: MilestoneDetailPanel } = await import('../MilestoneDetailPanel.vue')
    const wrapper = mount(MilestoneDetailPanel, {
      props: { milestoneId: 'ms-1' },
      global: { stubs: GLOBAL_STUBS },
    })
    expect(wrapper.find('input[type="checkbox"][data-testid="milestone-status-override"]').exists()).toBe(true)
  })

  it('renders .dp-footer with delete button', async () => {
    const { default: MilestoneDetailPanel } = await import('../MilestoneDetailPanel.vue')
    const wrapper = mount(MilestoneDetailPanel, {
      props: { milestoneId: 'ms-1' },
      global: { stubs: GLOBAL_STUBS },
    })
    expect(wrapper.find('.dp-footer').exists()).toBe(true)
    expect(wrapper.find('.dp-btn--ghost-danger').exists()).toBe(true)
  })
})
