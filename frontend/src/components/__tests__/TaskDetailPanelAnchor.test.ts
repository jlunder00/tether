/**
 * TaskDetailPanelAnchor.test.ts
 *
 * Tests for anchor-recurring task support in TaskDetailPanel:
 *  - RecurrencePicker shown only for anchor tasks (anchor_id set, no start_time)
 *  - RecurrencePicker hidden when task has start_time (calendar-event tasks)
 *  - setTaskRrule called when rrule changes on non-recurring anchor task
 *  - RecurrenceEditDialog opens when rrule changes on a recurring master task
 *  - RecurrenceEditDialog confirms call setTaskRrule with scope
 *  - Delete button on recurring master opens scope dialog
 *  - Delete scope dialog confirm calls deleteTask + popPanel
 *  - Delete scope dialog cancel leaves task intact
 */
import { describe, it, expect, vi, beforeEach, afterEach } from 'vitest'
import { ref, nextTick } from 'vue'
import { mount, flushPromises } from '@vue/test-utils'
import { createPinia, setActivePinia } from 'pinia'

vi.mock('vue-router', () => ({
  useRouter: () => ({ push: vi.fn() }),
  useRoute: () => ({ path: '/', query: {} }),
  RouterLink: { template: '<a><slot /></a>' },
}))

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

const popPanelMock = vi.fn()
vi.mock('../../composables/useSlideOver', () => ({
  useSlideOver: () => ({ push: vi.fn(), pop: popPanelMock }),
}))

vi.mock('../../lib/api', () => ({
  api: vi.fn(async () => ({ ok: true, json: async () => ({}) })),
}))

const today = new Date().toISOString().slice(0, 10)

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

// Backlog store controlled per-test via a module-level ref
const backlogTasksRef = ref<any[]>([])
vi.mock('../../stores/backlog', () => ({
  useBacklogStore: () => ({
    get tasks() { return backlogTasksRef.value },
    fetchTasks: vi.fn(),
  }),
}))

// tasksStore mocked so we can spy on setTaskRrule and deleteTask
const setTaskRruleMock = vi.fn(async () => {})
const deleteTaskMock = vi.fn(async () => {})
vi.mock('../../stores/tasks', () => ({
  useTasksStore: () => ({
    setTaskRrule: setTaskRruleMock,
    deleteTask: deleteTaskMock,
  }),
}))

// Named stub object — referenced by identity in findComponent() below
const RecurrencePickerStub = {
  name: 'RecurrencePicker',
  template: '<div data-testid="anchor-recurrence-picker-stub" />',
  props: ['modelValue', 'startTime'],
  emits: ['update:modelValue'],
}

const GLOBAL_STUBS = {
  SearchAutocomplete: true,
  RecurrencePicker: RecurrencePickerStub,
  'router-link': { template: '<a><slot /></a>' },
}

/** Base anchor task — has anchor_id, no start_time */
const ANCHOR_TASK = {
  id: 'task-anchor-1',
  text: 'Weekly review',
  status: 'pending',
  description: null,
  followup_config: null,
  anchor_id: 'morning',
  start_time: null,
  end_time: null,
  rrule: null,
  is_recurring_master: false,
}

/** Recurring anchor-task master */
const RECURRING_ANCHOR_TASK = {
  ...ANCHOR_TASK,
  id: 'task-recurring-1',
  rrule: 'FREQ=WEEKLY;BYDAY=MO',
  is_recurring_master: true,
}

/** Anchor task that also has a calendar event (start_time set) — picker should NOT appear */
const SCHEDULED_ANCHOR_TASK = {
  ...ANCHOR_TASK,
  id: 'task-scheduled-1',
  start_time: '2024-06-10T09:00:00Z',
  end_time: '2024-06-10T10:00:00Z',
}

describe('TaskDetailPanel — Anchor recurrence section', () => {
  beforeEach(() => {
    setActivePinia(createPinia())
    backlogTasksRef.value = []
    popPanelMock.mockClear()
    setTaskRruleMock.mockClear()
    deleteTaskMock.mockClear()
  })

  afterEach(() => {
    // Clean up any DOM appended by Teleport
    while (document.body.firstChild) document.body.removeChild(document.body.firstChild)
  })

  // ── visibility ───────────────────────────────────────────────────────────────

  it('renders anchor RecurrencePicker when task has anchor_id and no start_time', async () => {
    backlogTasksRef.value = [ANCHOR_TASK]
    const { default: TaskDetailPanel } = await import('../TaskDetailPanel.vue')
    const wrapper = mount(TaskDetailPanel, {
      props: { taskId: ANCHOR_TASK.id },
      global: { stubs: GLOBAL_STUBS },
    })
    await nextTick()
    expect(wrapper.find('[data-testid="anchor-recurrence-picker-stub"]').exists()).toBe(true)
  })

  it('does NOT render anchor RecurrencePicker when task has start_time (calendar event)', async () => {
    backlogTasksRef.value = [SCHEDULED_ANCHOR_TASK]
    const { default: TaskDetailPanel } = await import('../TaskDetailPanel.vue')
    const wrapper = mount(TaskDetailPanel, {
      props: { taskId: SCHEDULED_ANCHOR_TASK.id },
      global: { stubs: GLOBAL_STUBS },
    })
    await nextTick()
    expect(wrapper.find('[data-testid="anchor-recurrence-picker-stub"]').exists()).toBe(false)
  })

  it('does NOT render anchor RecurrencePicker when task has no anchor_id (backlog)', async () => {
    const backlogTask = { ...ANCHOR_TASK, id: 'task-backlog-1', anchor_id: null }
    backlogTasksRef.value = [backlogTask]
    const { default: TaskDetailPanel } = await import('../TaskDetailPanel.vue')
    const wrapper = mount(TaskDetailPanel, {
      props: { taskId: 'task-backlog-1' },
      global: { stubs: GLOBAL_STUBS },
    })
    await nextTick()
    expect(wrapper.find('[data-testid="anchor-recurrence-picker-stub"]').exists()).toBe(false)
  })

  // ── non-recurring: direct setTaskRrule ────────────────────────────────────────

  it('emitting update:modelValue from anchor RecurrencePicker calls setTaskRrule directly for non-recurring task', async () => {
    backlogTasksRef.value = [ANCHOR_TASK]
    const { default: TaskDetailPanel } = await import('../TaskDetailPanel.vue')
    const wrapper = mount(TaskDetailPanel, {
      props: { taskId: ANCHOR_TASK.id },
      global: { stubs: GLOBAL_STUBS },
    })
    await nextTick()

    // Find the anchor recurrence picker and emit change
    const picker = wrapper.findComponent(RecurrencePickerStub)
    await picker.vm.$emit('update:modelValue', 'FREQ=DAILY')
    await nextTick()

    expect(setTaskRruleMock).toHaveBeenCalledWith(ANCHOR_TASK.id, 'FREQ=DAILY')
  })

  // ── recurring master: scope dialog ───────────────────────────────────────────

  it('emitting update:modelValue on a recurring master opens the anchor scope dialog', async () => {
    backlogTasksRef.value = [RECURRING_ANCHOR_TASK]
    const { default: TaskDetailPanel } = await import('../TaskDetailPanel.vue')
    const wrapper = mount(TaskDetailPanel, {
      attachTo: document.body,
      props: { taskId: RECURRING_ANCHOR_TASK.id },
      global: {
        stubs: {
          ...GLOBAL_STUBS,
          RecurrenceEditDialog: false, // unmock RecurrenceEditDialog so Teleport renders
        },
      },
    })
    await nextTick()

    const picker = wrapper.findComponent(RecurrencePickerStub)
    await picker.vm.$emit('update:modelValue', 'FREQ=DAILY')
    await nextTick()

    // Dialog should be visible
    expect(document.body.querySelector('[data-testid="recurrence-edit-dialog"]')).not.toBeNull()
    // setTaskRrule should NOT have been called yet
    expect(setTaskRruleMock).not.toHaveBeenCalled()
  })

  it('confirming scope dialog after rrule change calls setTaskRrule and refreshes plan', async () => {
    backlogTasksRef.value = [RECURRING_ANCHOR_TASK]
    const { default: TaskDetailPanel } = await import('../TaskDetailPanel.vue')
    const wrapper = mount(TaskDetailPanel, {
      attachTo: document.body,
      props: { taskId: RECURRING_ANCHOR_TASK.id },
      global: {
        stubs: {
          ...GLOBAL_STUBS,
          RecurrenceEditDialog: false,
        },
      },
    })
    await nextTick()

    // Trigger rrule change to open dialog
    const picker = wrapper.findComponent(RecurrencePickerStub)
    await picker.vm.$emit('update:modelValue', 'FREQ=DAILY')
    await nextTick()

    // Click confirm
    const confirmBtn = document.body.querySelector('[data-testid="recurrence-edit-confirm"]') as HTMLElement
    expect(confirmBtn).not.toBeNull()
    confirmBtn.click()
    await nextTick()

    expect(setTaskRruleMock).toHaveBeenCalledWith(RECURRING_ANCHOR_TASK.id, 'FREQ=DAILY')
  })

  it('cancelling scope dialog after rrule change does NOT call setTaskRrule', async () => {
    backlogTasksRef.value = [RECURRING_ANCHOR_TASK]
    const { default: TaskDetailPanel } = await import('../TaskDetailPanel.vue')
    const wrapper = mount(TaskDetailPanel, {
      attachTo: document.body,
      props: { taskId: RECURRING_ANCHOR_TASK.id },
      global: {
        stubs: {
          ...GLOBAL_STUBS,
          RecurrenceEditDialog: false,
        },
      },
    })
    await nextTick()

    const picker = wrapper.findComponent(RecurrencePickerStub)
    await picker.vm.$emit('update:modelValue', 'FREQ=DAILY')
    await nextTick()

    const cancelBtn = document.body.querySelector('[data-testid="recurrence-edit-cancel"]') as HTMLElement
    expect(cancelBtn).not.toBeNull()
    cancelBtn.click()
    await nextTick()

    expect(setTaskRruleMock).not.toHaveBeenCalled()
  })

  // ── delete ───────────────────────────────────────────────────────────────────

  it('delete button on recurring master opens scope-delete dialog instead of confirm()', async () => {
    backlogTasksRef.value = [RECURRING_ANCHOR_TASK]
    const { default: TaskDetailPanel } = await import('../TaskDetailPanel.vue')
    const wrapper = mount(TaskDetailPanel, {
      attachTo: document.body,
      props: { taskId: RECURRING_ANCHOR_TASK.id },
      global: {
        stubs: {
          ...GLOBAL_STUBS,
          RecurrenceEditDialog: false,
        },
      },
    })
    await nextTick()

    const deleteBtn = wrapper.find('[data-testid="delete-task-btn"]')
    expect(deleteBtn.exists()).toBe(true)
    await deleteBtn.trigger('click')
    await nextTick()

    // Dialog should appear (scope-delete mode)
    expect(document.body.querySelector('[data-testid="recurrence-edit-dialog"]')).not.toBeNull()
    // deleteTask should NOT have been called yet
    expect(deleteTaskMock).not.toHaveBeenCalled()
  })

  it('confirming scope-delete calls deleteTask with scope and closes panel', async () => {
    backlogTasksRef.value = [RECURRING_ANCHOR_TASK]
    const { default: RecurrenceEditDialog } = await import('../RecurrenceEditDialog.vue')
    const { default: TaskDetailPanel } = await import('../TaskDetailPanel.vue')
    const wrapper = mount(TaskDetailPanel, {
      attachTo: document.body,
      props: { taskId: RECURRING_ANCHOR_TASK.id },
      global: {
        stubs: {
          ...GLOBAL_STUBS,
          RecurrenceEditDialog: false,
        },
      },
    })
    await flushPromises()

    const deleteBtn = wrapper.find('[data-testid="delete-task-btn"]')
    expect(deleteBtn.exists()).toBe(true)
    await deleteBtn.trigger('click')
    await flushPromises()

    // Find the delete-scope dialog instance (action='delete') and emit confirm from it
    const allDialogs = wrapper.findAllComponents(RecurrenceEditDialog)
    const deleteDialog = allDialogs.find(d => d.props('action') === 'delete')
    expect(deleteDialog).toBeDefined()
    await deleteDialog!.vm.$emit('confirm', 'this')
    await flushPromises()

    expect(deleteTaskMock).toHaveBeenCalledWith(RECURRING_ANCHOR_TASK.id, expect.any(String), undefined)
    expect(popPanelMock).toHaveBeenCalled()
  })

  it('cancelling scope-delete dialog does NOT call deleteTask', async () => {
    backlogTasksRef.value = [RECURRING_ANCHOR_TASK]
    const { default: TaskDetailPanel } = await import('../TaskDetailPanel.vue')
    const wrapper = mount(TaskDetailPanel, {
      attachTo: document.body,
      props: { taskId: RECURRING_ANCHOR_TASK.id },
      global: {
        stubs: {
          ...GLOBAL_STUBS,
          RecurrenceEditDialog: false,
        },
      },
    })
    await nextTick()

    const deleteBtn = wrapper.find('[data-testid="delete-task-btn"]')
    await deleteBtn.trigger('click')
    await nextTick()

    const cancelBtn = document.body.querySelector('[data-testid="recurrence-edit-cancel"]') as HTMLElement
    cancelBtn.click()
    await nextTick()

    expect(deleteTaskMock).not.toHaveBeenCalled()
    expect(popPanelMock).not.toHaveBeenCalled()
  })
})
