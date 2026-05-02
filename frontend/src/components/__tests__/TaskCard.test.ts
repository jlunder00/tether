import { describe, it, expect, vi, beforeEach } from 'vitest'
import { mount } from '@vue/test-utils'
import { createPinia, setActivePinia } from 'pinia'
import type { Task } from '../../stores/plan'
import TaskCard from '../TaskCard.vue'

// Mock vue-router (TaskCard uses useRouter + useRoute)
vi.mock('vue-router', () => ({
  useRouter: () => ({ push: vi.fn() }),
  useRoute: () => ({ path: '/kanban' }),
}))

const baseTask: Task = {
  id: 'task-1',
  text: 'Test task',
  description: null,
  status: 'pending',
  position: 0,
  followup_config: null,
  blocks: [],
  blocked_by: [],
  context_subject: null,
  context_node_id: null,
}

describe('TaskCard drag behavior', () => {
  beforeEach(() => {
    setActivePinia(createPinia())
  })

  // NOTE: TaskCard template has a fragment root (v-if calendar-event / v-else normal).
  // Tests use data-testid selectors to target the rendered element directly.

  it('sets draggable="true" when editable is false (kanban mode)', () => {
    const wrapper = mount(TaskCard, {
      props: { task: baseTask, editable: false },
    })
    expect(wrapper.find('[data-testid="task-card"]').attributes('draggable')).toBe('true')
  })

  it('sets draggable="false" when editable is true (plan mode)', () => {
    const wrapper = mount(TaskCard, {
      props: { task: baseTask, editable: true },
    })
    expect(wrapper.find('[data-testid="task-card"]').attributes('draggable')).toBe('false')
  })

  it('sets draggable="false" when task has no id', () => {
    const wrapper = mount(TaskCard, {
      props: { task: { ...baseTask, id: '' }, editable: false },
    })
    expect(wrapper.find('[data-testid="task-card"]').attributes('draggable')).toBe('false')
  })

  it('serializes superset payload (type, taskId, title) as text/plain on dragstart', async () => {
    const wrapper = mount(TaskCard, {
      props: { task: baseTask, editable: false },
    })
    const setData = vi.fn()
    await wrapper.find('[data-testid="task-card"]').trigger('dragstart', {
      dataTransfer: { setData, effectAllowed: '' },
    })
    expect(setData).toHaveBeenCalledWith('text/plain', expect.any(String))
    const [, raw] = setData.mock.calls[0]
    const payload = JSON.parse(raw)
    expect(payload.type).toBe('task')
    expect(payload.taskId).toBe('task-1')
    expect(payload.title).toBe('Test task')
  })

  it('does not serialize data when task has no id', async () => {
    const wrapper = mount(TaskCard, {
      props: { task: { ...baseTask, id: '' }, editable: false },
    })
    const setData = vi.fn()
    await wrapper.find('[data-testid="task-card"]').trigger('dragstart', {
      dataTransfer: { setData, effectAllowed: '' },
    })
    expect(setData).not.toHaveBeenCalled()
  })
})

describe('TaskCard mode prop', () => {
  beforeEach(() => {
    setActivePinia(createPinia())
  })

  it('renders without error when mode="plan" (default/no mode)', () => {
    const wrapper = mount(TaskCard, {
      props: { task: baseTask },
    })
    expect(wrapper.find('[data-testid="task-card"]').exists()).toBe(true)
  })

  it('renders without error when mode="kanban"', () => {
    const wrapper = mount(TaskCard, {
      props: { task: baseTask, mode: 'kanban' },
    })
    expect(wrapper.find('[data-testid="task-card"]').exists()).toBe(true)
  })

  it('renders calendar-event mode with absolute positioning style', () => {
    const wrapper = mount(TaskCard, {
      props: {
        task: baseTask,
        mode: 'calendar-event',
        topPx: 120,
        heightPx: 60,
      },
    })
    expect(wrapper.find('[data-testid="task-card-calendar-event"]').exists()).toBe(true)
    const style = wrapper.find('[data-testid="task-card-calendar-event"]').attributes('style')
    expect(style).toContain('top: 120px')
    expect(style).toContain('height: 60px')
  })

  it('calendar-event mode applies resolvedColor as background', () => {
    const wrapper = mount(TaskCard, {
      props: {
        task: baseTask,
        mode: 'calendar-event',
        topPx: 0,
        heightPx: 60,
        resolvedColor: '#6366f1',
      },
    })
    const el = wrapper.find('[data-testid="task-card-calendar-event"]')
    expect(el.attributes('style')).toContain('#6366f1')
  })

  it('calendar-event mode applies leftPercent and widthPercent to style', () => {
    const wrapper = mount(TaskCard, {
      props: {
        task: baseTask,
        mode: 'calendar-event',
        topPx: 0,
        heightPx: 60,
        leftPercent: 50,
        widthPercent: 50,
      },
    })
    const el = wrapper.find('[data-testid="task-card-calendar-event"]')
    const style = el.attributes('style') ?? ''
    expect(style).toContain('50%')
  })

  it('calendar-event mode displays task title', () => {
    const wrapper = mount(TaskCard, {
      props: {
        task: { ...baseTask, text: 'Stand-up meeting' },
        mode: 'calendar-event',
        topPx: 0,
        heightPx: 60,
      },
    })
    expect(wrapper.text()).toContain('Stand-up meeting')
  })
})

describe('TaskCard isDragging / source-hide behavior', () => {
  beforeEach(() => {
    setActivePinia(createPinia())
  })

  it('root element is visible (not hidden) by default', () => {
    const wrapper = mount(TaskCard, {
      props: { task: baseTask, editable: false },
    })
    // v-show="!isDragging" — isDragging starts false → display not none
    expect(wrapper.find('[data-testid="task-card"]').isVisible()).toBe(true)
  })

  it('root element is hidden via v-show while dragging', async () => {
    const wrapper = mount(TaskCard, {
      props: { task: baseTask, editable: false },
      attachTo: document.body,
    })
    const card = wrapper.find('[data-testid="task-card"]')
    const setData = vi.fn()
    await card.trigger('dragstart', {
      dataTransfer: { setData, effectAllowed: '' },
    })
    // After dragstart, isDragging=true → v-show="false" → display:none
    expect(card.isVisible()).toBe(false)
  })

  it('root element becomes visible again after dragend', async () => {
    const wrapper = mount(TaskCard, {
      props: { task: baseTask, editable: false },
      attachTo: document.body,
    })
    const card = wrapper.find('[data-testid="task-card"]')
    const setData = vi.fn()
    await card.trigger('dragstart', {
      dataTransfer: { setData, effectAllowed: '' },
    })
    await card.trigger('dragend')
    expect(card.isVisible()).toBe(true)
  })
})
