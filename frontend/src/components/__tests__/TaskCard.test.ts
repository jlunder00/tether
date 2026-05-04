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

  it('omits draggable attribute when editable is true (plan mode — lets parent wrapper govern)', () => {
    // HTML5 DnD: explicit draggable="false" on a child hard-blocks the parent's draggable="true".
    // When TaskCard is not the drag source (plan mode), the attribute must be absent so
    // AnchorBlock's outer wrapper div can own drag initiation.
    const wrapper = mount(TaskCard, {
      props: { task: baseTask, editable: true },
    })
    expect(wrapper.find('[data-testid="task-card"]').attributes('draggable')).toBeUndefined()
  })

  it('omits draggable attribute when task has no id', () => {
    const wrapper = mount(TaskCard, {
      props: { task: { ...baseTask, id: '' }, editable: false },
    })
    expect(wrapper.find('[data-testid="task-card"]').attributes('draggable')).toBeUndefined()
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

  it('calendar-event mode tether event: background driven by data-motif, not hex resolvedColor', () => {
    // Tether events ignore resolvedColor — motif CSS variable drives the background.
    const wrapper = mount(TaskCard, {
      props: {
        task: baseTask,
        mode: 'calendar-event',
        topPx: 0,
        heightPx: 60,
        resolvedColor: '#6366f1',
        // no event prop → isTetherEvent = true
      },
    })
    const el = wrapper.find('[data-testid="task-card-calendar-event"]')
    expect(el.attributes('data-motif')).toBe('anchor')  // null motif → anchor fallback
    expect(el.attributes('style')).not.toContain('#6366f1')  // hex not used
    expect(el.attributes('style')).toContain('var(--m)')
  })

  it('calendar-event mode non-tether event: resolvedColor hex drives background', () => {
    // Google Calendar events have no motif — use resolvedColor directly.
    const googleEvent = {
      id: 'ev-gcal',
      title: 'GCal event',
      start_time: '2024-06-10T09:00:00',
      end_time: '2024-06-10T10:00:00',
      source: 'google_calendar' as const,
      external_id: null,
      task_id: null,
      anchor_id: null,
      color: null,
      is_recurring: false,
      is_occurrence: false,
      rrule: null,
      is_all_day: false,
      context_subject: null,
    }
    const wrapper = mount(TaskCard, {
      props: {
        task: baseTask,
        mode: 'calendar-event',
        topPx: 0,
        heightPx: 60,
        event: googleEvent,
        resolvedColor: '#4285f4',
      },
    })
    const el = wrapper.find('[data-testid="task-card-calendar-event"]')
    expect(el.attributes('data-motif')).toBeUndefined()  // non-tether: no motif attr
    expect(el.attributes('style')).toContain('#4285f4')
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

describe('TaskCard plan mode compact layout', () => {
  beforeEach(() => {
    setActivePinia(createPinia())
  })

  // TDD: these tests define the target compact list layout for plan mode.
  // Status glyphs replace the old absolute-positioned status pill.

  it('renders a status glyph button in plan mode', () => {
    const wrapper = mount(TaskCard, {
      props: { task: baseTask, mode: 'plan' },
    })
    expect(wrapper.find('[data-testid="plan-status-glyph"]').exists()).toBe(true)
  })

  // Glyph characters are injected via CSS ::before / --glyph-* custom properties
  // (see themes.css), so jsdom cannot observe the rendered character. We test the
  // CSS class applied to the button instead — the class drives the right ::before rule.

  it('applies status-glyph-pending class for pending status', () => {
    const wrapper = mount(TaskCard, {
      props: { task: baseTask, mode: 'plan' },
    })
    expect(wrapper.find('[data-testid="plan-status-glyph"]').classes()).toContain('status-glyph-pending')
  })

  it('applies status-glyph-in_progress class for in_progress status', () => {
    const wrapper = mount(TaskCard, {
      props: { task: { ...baseTask, status: 'in_progress' }, mode: 'plan' },
    })
    expect(wrapper.find('[data-testid="plan-status-glyph"]').classes()).toContain('status-glyph-in_progress')
  })

  it('applies status-glyph-done class for done status', () => {
    const wrapper = mount(TaskCard, {
      props: { task: { ...baseTask, status: 'done' }, mode: 'plan' },
    })
    expect(wrapper.find('[data-testid="plan-status-glyph"]').classes()).toContain('status-glyph-done')
  })

  it('applies status-glyph-skipped class for skipped status', () => {
    const wrapper = mount(TaskCard, {
      props: { task: { ...baseTask, status: 'skipped' }, mode: 'plan' },
    })
    expect(wrapper.find('[data-testid="plan-status-glyph"]').classes()).toContain('status-glyph-skipped')
  })

  it('applies status-glyph-blocked class for blocked status', () => {
    const wrapper = mount(TaskCard, {
      props: { task: { ...baseTask, status: 'blocked' }, mode: 'plan' },
    })
    expect(wrapper.find('[data-testid="plan-status-glyph"]').classes()).toContain('status-glyph-blocked')
  })

  it('clicking glyph cycles status from pending → in_progress', async () => {
    const wrapper = mount(TaskCard, {
      props: { task: baseTask, mode: 'plan', editable: true },
    })
    await wrapper.find('[data-testid="plan-status-glyph"]').trigger('click')
    const updateEvents = wrapper.emitted('update')
    expect(updateEvents).toBeTruthy()
    expect((updateEvents![0][0] as Task).status).toBe('in_progress')
  })

  it('clicking glyph cycles status from done → skipped', async () => {
    const wrapper = mount(TaskCard, {
      props: { task: { ...baseTask, status: 'done' }, mode: 'plan', editable: true },
    })
    await wrapper.find('[data-testid="plan-status-glyph"]').trigger('click')
    const updateEvents = wrapper.emitted('update')
    expect((updateEvents![0][0] as Task).status).toBe('skipped')
  })

  it('clicking glyph cycles status from blocked → pending (wrap-around)', async () => {
    const wrapper = mount(TaskCard, {
      props: { task: { ...baseTask, status: 'blocked' }, mode: 'plan', editable: true },
    })
    await wrapper.find('[data-testid="plan-status-glyph"]').trigger('click')
    const updateEvents = wrapper.emitted('update')
    expect((updateEvents![0][0] as Task).status).toBe('pending')
  })

  it('does not show old status pill in plan mode', () => {
    const wrapper = mount(TaskCard, {
      props: { task: baseTask, mode: 'plan' },
    })
    expect(wrapper.find('[data-testid="task-card-status-pill"]').exists()).toBe(false)
  })

  it('kanban mode still shows status pill, not status glyph', () => {
    const wrapper = mount(TaskCard, {
      props: { task: baseTask, mode: 'kanban' },
    })
    expect(wrapper.find('[data-testid="plan-status-glyph"]').exists()).toBe(false)
    expect(wrapper.find('[data-testid="task-card-status-pill"]').exists()).toBe(true)
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

  it('root element is hidden via v-show while dragging (after rAF fires)', async () => {
    const wrapper = mount(TaskCard, {
      props: { task: baseTask, editable: false },
      attachTo: document.body,
    })
    const card = wrapper.find('[data-testid="task-card"]')
    const setData = vi.fn()
    await card.trigger('dragstart', {
      dataTransfer: { setData, effectAllowed: '' },
    })
    // Advance rAF so source-hiding applies (isDragging=true → v-show="false")
    await new Promise(r => requestAnimationFrame(r))
    await wrapper.vm.$nextTick()
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
    await new Promise(r => requestAnimationFrame(r))
    await wrapper.vm.$nextTick()
    await card.trigger('dragend')
    expect(card.isVisible()).toBe(true)
  })
})
