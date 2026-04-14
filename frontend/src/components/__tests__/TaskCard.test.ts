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

  it('sets draggable="true" when editable is false (kanban mode)', () => {
    const wrapper = mount(TaskCard, {
      props: { task: baseTask, editable: false },
    })
    expect(wrapper.attributes('draggable')).toBe('true')
  })

  it('sets draggable="false" when editable is true (plan mode)', () => {
    const wrapper = mount(TaskCard, {
      props: { task: baseTask, editable: true },
    })
    expect(wrapper.attributes('draggable')).toBe('false')
  })

  it('sets draggable="false" when task has no id', () => {
    const wrapper = mount(TaskCard, {
      props: { task: { ...baseTask, id: '' }, editable: false },
    })
    expect(wrapper.attributes('draggable')).toBe('false')
  })

  it('serializes taskId as text/plain on dragstart', async () => {
    const wrapper = mount(TaskCard, {
      props: { task: baseTask, editable: false },
    })
    const setData = vi.fn()
    await wrapper.trigger('dragstart', {
      dataTransfer: { setData, effectAllowed: '' },
    })
    expect(setData).toHaveBeenCalledWith(
      'text/plain',
      JSON.stringify({ taskId: 'task-1' }),
    )
  })

  it('does not serialize data when task has no id', async () => {
    const wrapper = mount(TaskCard, {
      props: { task: { ...baseTask, id: '' }, editable: false },
    })
    const setData = vi.fn()
    await wrapper.trigger('dragstart', {
      dataTransfer: { setData, effectAllowed: '' },
    })
    expect(setData).not.toHaveBeenCalled()
  })
})
