/**
 * Track 3: PlanWeekCell — useDraggableTask on task items + useDropZone migration
 */
import { describe, it, expect, vi, beforeEach } from 'vitest'
import { mount } from '@vue/test-utils'
import { createPinia, setActivePinia } from 'pinia'
import { ref } from 'vue'

vi.mock('vue-router', () => ({
  useRouter: () => ({ push: vi.fn() }),
  useRoute: () => ({ path: '/' }),
}))

vi.mock('../../lib/api', () => ({
  api: vi.fn(() => Promise.resolve({ ok: true, json: async () => ({}) })),
}))

vi.mock('../TaskCard.vue', () => ({
  default: { template: '<div data-testid="task-card-stub" />' },
}))

const mockIsOver = ref(false)
vi.mock('../../composables/useDropZone', () => ({
  useDropZone: vi.fn(() => ({
    isOver: mockIsOver,
    dropHandlers: {
      onDragEnter: vi.fn(),
      onDragOver: vi.fn(),
      onDragLeave: vi.fn(),
      onDrop: vi.fn(),
    },
  })),
}))

describe('PlanWeekCell — useDropZone migration (Track 3)', () => {
  beforeEach(() => {
    setActivePinia(createPinia())
    vi.clearAllMocks()
    mockIsOver.value = false
  })

  async function mountCell(props: Record<string, unknown> = {}) {
    const { default: PlanWeekCell } = await import('../plan/PlanWeekCell.vue')
    return mount(PlanWeekCell, {
      props: {
        date: '2026-05-05',
        anchorId: 'anchor-deep-work',
        anchorName: 'Deep Work',
        tasks: [],
        ...props,
      },
    })
  }

  it('applies ring-1 highlight when isOver is true', async () => {
    const w = await mountCell()
    const drop = w.find('[data-testid="week-cell-drop"]')

    mockIsOver.value = true
    await w.vm.$nextTick()

    expect(drop.classes()).toContain('ring-1')
  })

  it('removes ring-1 when isOver is false', async () => {
    const w = await mountCell()
    const drop = w.find('[data-testid="week-cell-drop"]')

    mockIsOver.value = false
    await w.vm.$nextTick()

    expect(drop.classes()).not.toContain('ring-1')
  })

  it('does not expose a manual isDragOver ref (replaced by useDropZone)', async () => {
    const w = await mountCell()
    expect((w.vm as any).isDragOver).toBeUndefined()
  })
})

describe('PlanWeekCell — draggable task wrappers (Track 3)', () => {
  const taskFixture = {
    id: 'task-abc',
    text: 'Draggable task',
    status: 'pending' as const,
    position: 0,
    description: null,
    followup_config: null,
    blocks: [],
    blocked_by: [],
    context_subject: null,
    context_node_id: null,
  }

  beforeEach(() => {
    setActivePinia(createPinia())
    vi.clearAllMocks()
    mockIsOver.value = false
  })

  async function mountCell(tasks = [taskFixture]) {
    const { default: PlanWeekCell } = await import('../plan/PlanWeekCell.vue')
    return mount(PlanWeekCell, {
      props: {
        date: '2026-05-05',
        anchorId: 'anchor-deep-work',
        anchorName: 'Deep Work',
        tasks,
      },
      attachTo: document.body,
    })
  }

  it('task wrapper div has draggable=true', async () => {
    const w = await mountCell()
    const wrapper = w.find('[data-task-id="task-abc"]')
    expect(wrapper.exists()).toBe(true)
    expect(wrapper.attributes('draggable')).toBe('true')
  })

  it('task wrapper is visible before drag starts', async () => {
    const w = await mountCell()
    const wrapper = w.find('[data-task-id="task-abc"]')
    expect(wrapper.isVisible()).toBe(true)
  })

  it('task wrapper is hidden while dragging (v-show=false after dragstart)', async () => {
    const w = await mountCell()
    const wrapper = w.find('[data-task-id="task-abc"]')

    await wrapper.trigger('dragstart', {
      dataTransfer: { effectAllowed: '', setData: vi.fn() },
    })

    expect(wrapper.isVisible()).toBe(false)
  })

  it('task wrapper is visible again after dragend', async () => {
    const w = await mountCell()
    const wrapper = w.find('[data-task-id="task-abc"]')

    await wrapper.trigger('dragstart', {
      dataTransfer: { effectAllowed: '', setData: vi.fn() },
    })
    await wrapper.trigger('dragend')

    expect(wrapper.isVisible()).toBe(true)
  })

  it('dragstart writes superset payload with type:task, taskId, fromDate, fromAnchorId', async () => {
    const w = await mountCell()
    const wrapper = w.find('[data-task-id="task-abc"]')
    const setData = vi.fn()

    await wrapper.trigger('dragstart', {
      dataTransfer: { effectAllowed: '', setData },
    })

    expect(setData).toHaveBeenCalledOnce()
    const payload = JSON.parse(setData.mock.calls[0][1])
    expect(payload.type).toBe('task')
    expect(payload.taskId).toBe('task-abc')
    expect(payload.fromDate).toBe('2026-05-05')
    expect(payload.fromAnchorId).toBe('anchor-deep-work')
  })
})
