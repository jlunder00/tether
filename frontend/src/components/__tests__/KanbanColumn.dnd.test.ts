/**
 * Track 3: KanbanColumn — useDropZone migration + source task hiding
 */
import { describe, it, expect, vi, beforeEach } from 'vitest'
import { mount } from '@vue/test-utils'
import { createPinia, setActivePinia } from 'pinia'
import KanbanColumn from '../KanbanColumn.vue'
import type { KanbanColumn as KanbanColumnType } from '../../stores/kanban'
import { ref } from 'vue'

vi.mock('../../lib/api', () => ({
  api: vi.fn(() => Promise.resolve({ ok: true, json: () => Promise.resolve({}) })),
}))

// Mock useDropZone so we can test isOver binding without needing real DnD events
const mockIsOver = ref(false)
const mockDropHandlers = {
  onDragEnter: vi.fn(),
  onDragOver: vi.fn(),
  onDragLeave: vi.fn(),
  onDrop: vi.fn(),
}
vi.mock('../../composables/useDropZone', () => ({
  useDropZone: vi.fn(() => ({
    isOver: mockIsOver,
    dropHandlers: mockDropHandlers,
  })),
}))

const testColumn: KanbanColumnType = {
  id: 'col_done',
  name: 'Done',
  position: 3,
  color: '#22c55e',
  match_rules: { status: 'done' },
  entry_rules: { set_status: 'done' },
  created_by: null,
}

describe('KanbanColumn — useDropZone (Track 3)', () => {
  beforeEach(() => {
    setActivePinia(createPinia())
    vi.clearAllMocks()
    mockIsOver.value = false
  })

  it('applies ring highlight class when isOver is true', async () => {
    const w = mount(KanbanColumn, { props: { column: testColumn, tasks: [] } })
    const body = w.find('.flex-1.overflow-y-auto')

    mockIsOver.value = true
    await w.vm.$nextTick()

    expect(body.classes()).toContain('ring-2')
  })

  it('removes ring class when isOver is false', async () => {
    const w = mount(KanbanColumn, { props: { column: testColumn, tasks: [] } })
    const body = w.find('.flex-1.overflow-y-auto')

    mockIsOver.value = false
    await w.vm.$nextTick()

    expect(body.classes()).not.toContain('ring-2')
  })

  it('does not expose a manual dragEnterCount ref (replaced by useDropZone)', () => {
    const w = mount(KanbanColumn, { props: { column: testColumn, tasks: [] } })
    // The vm should not have dragEnterCount — it has been removed
    expect((w.vm as any).dragEnterCount).toBeUndefined()
  })

  it('emits task-drop when drop handler receives a valid task payload', async () => {
    const { useDropZone } = await import('../../composables/useDropZone')
    const mockUseDropZone = vi.mocked(useDropZone)
    let capturedOnDrop: ((payload: unknown, ctx: unknown) => void) | null = null
    mockUseDropZone.mockImplementationOnce((opts: any) => {
      capturedOnDrop = opts.onDrop
      return { isOver: ref(false), dropHandlers: mockDropHandlers }
    })

    const w = mount(KanbanColumn, { props: { column: testColumn, tasks: [] } })

    capturedOnDrop!({ taskId: 'task-99' }, undefined)
    await w.vm.$nextTick()

    expect(w.emitted('task-drop')).toBeTruthy()
    expect(w.emitted('task-drop')![0]).toEqual(['task-99', 'col_done'])
  })

  it('does not emit task-drop when payload has no taskId', async () => {
    const { useDropZone } = await import('../../composables/useDropZone')
    const mockUseDropZone = vi.mocked(useDropZone)
    let capturedOnDrop: ((payload: unknown, ctx: unknown) => void) | null = null
    mockUseDropZone.mockImplementationOnce((opts: any) => {
      capturedOnDrop = opts.onDrop
      return { isOver: ref(false), dropHandlers: mockDropHandlers }
    })

    const w = mount(KanbanColumn, { props: { column: testColumn, tasks: [] } })
    capturedOnDrop!({}, undefined)

    expect(w.emitted('task-drop')).toBeFalsy()
  })
})

describe('KanbanColumn — source task hiding (Track 3)', () => {
  const taskFixture = {
    id: 'task-1',
    text: 'Test task',
    status: 'pending' as const,
    position: 0,
    description: null,
    followup_config: null,
    blocks: [],
    blocked_by: [],
    context_subject: null,
    context_node_id: null,
    plan_date: null,
    anchor_id: null,
  }

  beforeEach(() => {
    setActivePinia(createPinia())
    vi.clearAllMocks()
    mockIsOver.value = false
  })

  it('task wrapper has draggable=true', () => {
    const w = mount(KanbanColumn, {
      props: { column: testColumn, tasks: [taskFixture] },
    })
    const wrapper = w.find('[data-task-id="task-1"]')
    expect(wrapper.exists()).toBe(true)
    expect(wrapper.attributes('draggable')).toBe('true')
  })

  it('task wrapper is visible before drag starts', () => {
    const w = mount(KanbanColumn, {
      props: { column: testColumn, tasks: [taskFixture] },
    })
    const wrapper = w.find('[data-task-id="task-1"]')
    expect(wrapper.isVisible()).toBe(true)
  })

  it('task wrapper is hidden while dragging (v-show=false after dragstart + rAF)', async () => {
    const w = mount(KanbanColumn, {
      props: { column: testColumn, tasks: [taskFixture] },
      attachTo: document.body,
    })
    const wrapper = w.find('[data-task-id="task-1"]')

    await wrapper.trigger('dragstart', {
      dataTransfer: { effectAllowed: '', setData: vi.fn() },
    })
    // Advance rAF so source-hiding applies
    await new Promise(r => requestAnimationFrame(r))
    await w.vm.$nextTick()

    expect(wrapper.isVisible()).toBe(false)
  })

  it('task wrapper is visible again after dragend', async () => {
    const w = mount(KanbanColumn, {
      props: { column: testColumn, tasks: [taskFixture] },
      attachTo: document.body,
    })
    const wrapper = w.find('[data-task-id="task-1"]')

    await wrapper.trigger('dragstart', {
      dataTransfer: { effectAllowed: '', setData: vi.fn() },
    })
    await new Promise(r => requestAnimationFrame(r))
    await w.vm.$nextTick()
    await wrapper.trigger('dragend')

    expect(wrapper.isVisible()).toBe(true)
  })

  it('task wrapper is still visible immediately after dragstart (ghost capture window — rAF not yet fired)', async () => {
    // Source hiding must be deferred via rAF so the browser can capture a
    // visible ghost image before the element is hidden.
    const rafCallbacks: FrameRequestCallback[] = []
    vi.spyOn(window, 'requestAnimationFrame').mockImplementation((cb) => {
      rafCallbacks.push(cb)
      return 0
    })

    const w = mount(KanbanColumn, {
      props: { column: testColumn, tasks: [taskFixture] },
      attachTo: document.body,
    })
    const wrapper = w.find('[data-task-id="task-1"]')

    await wrapper.trigger('dragstart', {
      dataTransfer: { effectAllowed: '', setData: vi.fn() },
    })

    // Ghost capture window: must be visible before rAF fires
    expect(wrapper.isVisible()).toBe(true)

    // Fire rAF → hiding applies
    rafCallbacks.forEach(cb => cb(0))
    await w.vm.$nextTick()
    expect(wrapper.isVisible()).toBe(false)

    vi.restoreAllMocks()
  })
})
